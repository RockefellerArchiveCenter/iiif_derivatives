import json
import logging
import math
import subprocess
import tarfile
import traceback
from os import getenv
from pathlib import Path

import boto3
from aws_assume_role_lib import assume_role
from PIL import Image

from .clients import ZodiacClient

Image.MAX_IMAGE_PIXELS = getenv('MAX_IMAGE_PIXELS')

logging.basicConfig(
    level=int(getenv('LOGGING_LEVEL', logging.INFO)),
    format='%(filename)s::%(funcName)s::%(lineno)s %(message)s')


class DerivativeMaker(object):

    def __init__(
            self,
            package_id,
            aws_region,
            aws_role_arn,
            zodiac_baseurl,
            tmp_dir,
            source_bucket,
            destination_bucket,
            sns_topic):
        self.package_id = package_id
        self.aws_region = aws_region
        self.aws_role_arn = aws_role_arn
        self.tmp_dir = tmp_dir
        self.source_bucket = source_bucket
        self.destination_bucket = destination_bucket
        self.sns_topic = sns_topic
        self.zodiac_client = ZodiacClient(zodiac_baseurl)
        self.service_name = 'iiif_derivatives'

    def run(self):
        try:
            self.send_start_message()
            package_data = self.zodiac_client.get(f'packages/{self.package_id}')
            dimes_id = package_data['identifiers']['dimes_object']
            download_path = self.download_package(self.package_id)
            extracted_path = self.extract_package(download_path)
            self.convert_to_stripped_tiff(extracted_path)
            jp2_dir = self.create_jp2_files(extracted_path, dimes_id)
            self.upload_jp2_files(jp2_dir)
            self.cleanup_successful(self.package_id)
            self.send_success_message(package_data)
        except Exception as e:
            logging.error(e)
            self.send_failure_message(e)

    def get_client_with_role(self, resource, role_arn):
        """Gets Boto3 client which authenticates with a specific IAM role."""
        session = boto3.Session()
        assumed_role_session = assume_role(session, role_arn)
        return assumed_role_session.client(resource)

    def download_package(self, package_id):
        """Downloads package from S3 bucket.

        Args:
            package_id (str): Identifier of package to download.

        Returns:
            download_path (pathlib.Path): Location of downloaded package.
        """
        client = self.get_client_with_role('s3', self.aws_role_arn)
        download_path = Path(self.tmp_dir, f'{package_id}.tar.gz')
        client.download_file(
            self.source_bucket,
            f"{package_id}.tar.gz",
            download_path)
        return download_path

    def extract_package(self, archive_path):
        """Extracts tarballed package.

        Args:
            archive_path (pathlib.Path): Location of package to be extracted.

        Returns:
            extracted_path (pathlib.Path): Location of extracted package.
        """
        with tarfile.open(archive_path, "r:*") as tf:
            tf.extractall(self.tmp_dir)
        return Path(self.tmp_dir, self.package_id)

    def convert_to_stripped_tiff(self, package_path):
        """Prepares TIFFs for JPEG2000 processing.

        Args:
            package_path (pathlib.Path): path of package
        """
        tiff_dir = package_path / 'data' / 'service'
        for tiff in tiff_dir.iterdir():
            if tiff.suffix == '.tif':
                print(f"converting  to strips {tiff}")
                tmp_tiff = tiff.with_stem(f'{tiff.stem}__stripped')
                cmd = ["tiffcp", "-s", tiff, tmp_tiff]
                subprocess.run(cmd, check=True)
                tmp_tiff.rename(tiff)

    def get_page_number(self, filename):
        """Parses a page number from a filename.

        Presumes that:
            The page number is preceded by an underscore
            The page number is immediately followed by either by `_m`, `_me` or `_se`,
            or the file extension.

        Args:
            file (str): filename of a TIFF image file.
        Returns:
            4-digit page number from the filename with leading zeroes
        """
        base_filename = Path(filename).stem
        if "_se" in base_filename:
            filename_trimmed = base_filename.split("_se")[0]
        elif "_m" in base_filename:
            filename_trimmed = base_filename.split("_m")[0]
        else:
            filename_trimmed = base_filename
        return filename_trimmed.split("_")[-1].lstrip("0").zfill(4)

    def calculate_layers(self, fp):
        """Calculates the number of layers based on pixel dimensions.
        For TIFF files, image tag 256 is the width, and 257 is the height.

        Args:
            fp (str): filename of a TIFF image file.
        Returns:
            layers (int): number of layers to convert to
        """
        try:
            with Image.open(fp) as img:
                width = [w for w in img.tag[256]][0]
                height = [h for h in img.tag[257]][0]
            return math.ceil(
                (math.log(max(width, height)) / math.log(2)) - ((math.log(96) / math.log(2)))) + 1
        except Exception:
            client = self.get_client_with_role('s3', self.aws_role_arn)
            client.upload_file(
                str(fp),
                self.destination_bucket,
                fp.name)
            raise

    def create_jp2_files(self, package_path, dimes_id):
        """Creates JPEG2000 files from TIFF files.

        The default options for conversion below are:
        - Compression ration of `1.5`
        - Precinct size: `[256,256]` for first two layers and then `[128,128]` for all others
        - Code block size of `[64,64]`
        - Progression order of `RPCL`

        Args:
            package_path (pathlib.Path): Location of package.
            dimes_id (str): The identifier for the package in DIMES.

        Returns:
            jp2_list: A tuple of JPG2000 paths including their page numbers
        """

        default_options = ["-r", "1.5",
                           "-c", "[256,256],[256,256],[128,128]",
                           "-b", "64,64",
                           "-p", "RPCL"]
        tiff_dir = package_path / 'data' / 'service'
        jp2_dir = Path(self.tmp_dir, 'jp2')
        jp2_dir.mkdir()
        for tiff_file in tiff_dir.iterdir():
            if tiff_file.suffix == '.tif':
                print(f"converting to JP2: {tiff_file}")
                page_number = self.get_page_number(str(tiff_file))
                jp2_path = jp2_dir / f'{dimes_id}_{page_number}.jp2'
                layers = self.calculate_layers(tiff_file)
                cmd = ['opj_compress',
                       "-i", str(tiff_file),
                       "-o", str(jp2_path),
                       "-n", str(layers),
                       "-SOP"] + default_options
                subprocess.run(cmd, check=True)
        return jp2_dir

    def upload_jp2_files(self, jp2_dir):
        """Uploads JPEG 2000 files to destnation.

        Args:
            jp2_dir (pathlib.Path): Directory containing JPEG2000 files.
        """
        client = self.get_client_with_role('s3', self.aws_role_arn)
        for fp in jp2_dir.iterdir():
            logging.info(f'uploading {str(fp)} to {fp.name} in {self.destination_bucket}')
            client.upload_file(
                str(fp),
                self.destination_bucket,
                f'images/{fp.name}')

    def cleanup_successful(self, package_id):
        """Removes package from source bucket.

        Args:
            package_id (str): Identifier of package to be removed.
        """
        client = self.get_client_with_role('s3', self.aws_role_arn)
        client.delete_object(Bucket=self.source_bucket, Key=f'{package_id}.tar.gz')

    def send_start_message(self):
        """Sends start message to SNS topic."""
        client = self.get_client_with_role('sns', self.aws_role_arn)
        client.publish(
            TopicArn=self.sns_topic,
            MessageGroupId=f'{self.service_name}-{self.package_id}',
            MessageDeduplicationId=f'{self.service_name}-{self.package_id}-start',
            Message='IIIF derivative creation started.',
            MessageAttributes={
                'package_id': {
                    'DataType': 'String',
                    'StringValue': self.package_id,
                },
                'service': {
                    'DataType': 'String',
                    'StringValue': self.service_name,
                },
                'outcome': {
                    'DataType': 'String',
                    'StringValue': 'STARTED',
                },
                'message': {
                    'DataType': 'String',
                    'StringValue': 'IIIF derivative creation started.',
                }
            })
        logging.debug('Start notification delivered.')

    def send_success_message(self, package_data):
        """Send SNS message about successful job."""
        client = self.get_client_with_role('sns', self.aws_role_arn)
        client.publish(
            TopicArn=self.sns_topic,
            MessageGroupId=f'{self.service_name}-{self.package_id}',
            MessageDeduplicationId=f'{self.service_name}-{self.package_id}-success',
            Message=json.dumps(package_data, default=str),
            MessageAttributes={
                'package_id': {
                    'DataType': 'String',
                    'StringValue': self.package_id,
                },
                'service': {
                    'DataType': 'String',
                    'StringValue': self.service_name,
                },
                'outcome': {
                    'DataType': 'String',
                    'StringValue': 'SUCCESS',
                },
                'message': {
                    'DataType': 'String',
                    'StringValue': 'IIIF derivatives created.',
                },
            })
        logging.debug('Success notification delivered.')

    def send_failure_message(self, exception):
        """Send SNS message about failed job.

        Args:
            exception (Exception): the exception that was thrown.
        """
        client = self.get_client_with_role('sns', self.aws_role_arn)
        tb = ''.join(traceback.format_exception(exception)[:-1])
        client.publish(
            TopicArn=self.sns_topic,
            MessageGroupId=f'{self.service_name}-{self.package_id}',
            MessageDeduplicationId=f'{self.service_name}-{self.package_id}-failure',
            Message=tb,
            MessageAttributes={
                'package_id': {
                    'DataType': 'String',
                    'StringValue': self.package_id,
                },
                'service': {
                    'DataType': 'String',
                    'StringValue': self.service_name,
                },
                'outcome': {
                    'DataType': 'String',
                    'StringValue': 'FAILURE',
                },
                'message': {
                    'DataType': 'String',
                    'StringValue': str(exception),
                }
            })
        logging.debug('Failure notification delivered.')


if __name__ == '__main__':
    package_id = getenv('PACKAGE_ID')
    region = getenv('AWS_REGION')
    role_arn = getenv('AWS_ROLE_ARN')
    zodiac_baseurl = getenv('ZODIAC_BASEURL')
    tmp_dir = getenv('TMP_DIR')
    source_bucket = getenv('AWS_SOURCE_BUCKET')
    destination_bucket = getenv('AWS_DESTINATION_BUCKET')
    sns_topic = getenv('AWS_SNS_TOPIC')

    DerivativeMaker(
        package_id,
        region,
        role_arn,
        zodiac_baseurl,
        tmp_dir,
        source_bucket,
        destination_bucket,
        sns_topic).run()
