import json
import shutil
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws
from moto.core import DEFAULT_ACCOUNT_ID

from src.create_derivatives import DerivativeMaker

DEFAULT_ARGS = ['0edb4066-980c-491f-bd73-c80a6546ff6d',
                'us-east-1',
                'arn:aws:iam::123456789012:role/iiif-derivatives-role',
                'https://zodiac-backend.dev.rockarch.org',
                '/ebs',
                'rac-dev-pictor-upload',
                'raciiif-dev',
                'sns-topic']


class InitTests(TestCase):

    @patch('src.clients.ZodiacClient.__init__')
    def test_init(self, mock_zodiac):
        mock_zodiac.return_value = None
        derivative_maker = DerivativeMaker(*DEFAULT_ARGS)
        mock_zodiac.assert_called_once_with(DEFAULT_ARGS[3])
        self.assertEqual(derivative_maker.package_id, DEFAULT_ARGS[0])
        self.assertEqual(derivative_maker.aws_region, DEFAULT_ARGS[1])
        self.assertEqual(derivative_maker.aws_role_arn, DEFAULT_ARGS[2])
        self.assertEqual(derivative_maker.tmp_dir, DEFAULT_ARGS[4])
        self.assertEqual(derivative_maker.source_bucket, DEFAULT_ARGS[5])
        self.assertEqual(derivative_maker.destination_bucket, DEFAULT_ARGS[6])
        self.assertEqual(derivative_maker.sns_topic, DEFAULT_ARGS[7])


class MethodTests(TestCase):

    def setUp(self):
        self.derivative_maker = DerivativeMaker(*DEFAULT_ARGS)
        Path(self.derivative_maker.tmp_dir).mkdir(parents=True)

    @patch('src.create_derivatives.DerivativeMaker.send_start_message')
    @patch('src.clients.ZodiacClient.get')
    @patch('src.create_derivatives.DerivativeMaker.download_package')
    @patch('src.create_derivatives.DerivativeMaker.extract_package')
    @patch('src.create_derivatives.DerivativeMaker.convert_to_stripped_tiff')
    @patch('src.create_derivatives.DerivativeMaker.create_jp2_files')
    @patch('src.create_derivatives.DerivativeMaker.upload_jp2_files')
    @patch('src.create_derivatives.DerivativeMaker.cleanup_successful')
    @patch('src.create_derivatives.DerivativeMaker.send_success_message')
    @patch('src.create_derivatives.DerivativeMaker.send_failure_message')
    def test_run(self, mock_failure_message, mock_success_message, mock_cleanup, mock_upload,
                 mock_create, mock_stripped, mock_extract, mock_download, mock_data, mock_start_message):
        package_data = {'identifiers': {'dimes_object': 'YRa9EbvFzk9qcLdrsEhK6u'}}
        mock_data.return_value = package_data
        downloaded_path = Path("downloaded")
        mock_download.return_value = downloaded_path
        extracted_path = Path("extracted")
        mock_extract.return_value = extracted_path
        jp2_dir = Path("jp2")
        mock_create.return_value = jp2_dir
        self.derivative_maker.run()
        mock_failure_message.assert_not_called()
        mock_success_message.assert_called_once_with(package_data)
        mock_cleanup.assert_called_once_with(self.derivative_maker.package_id)
        mock_upload.assert_called_once_with(jp2_dir)
        mock_create.assert_called_once_with(extracted_path, 'YRa9EbvFzk9qcLdrsEhK6u')
        mock_stripped.assert_called_once()
        mock_extract.assert_called_once_with(downloaded_path)
        mock_download.assert_called_once_with(self.derivative_maker.package_id)
        mock_data.assert_called_once_with(f'packages/{self.derivative_maker.package_id}')
        mock_start_message.assert_called_once_with()

    @patch('src.create_derivatives.DerivativeMaker.send_start_message')
    @patch('src.clients.ZodiacClient.get')
    @patch('src.create_derivatives.DerivativeMaker.download_package')
    @patch('src.create_derivatives.DerivativeMaker.extract_package')
    @patch('src.create_derivatives.DerivativeMaker.convert_to_stripped_tiff')
    @patch('src.create_derivatives.DerivativeMaker.create_jp2_files')
    @patch('src.create_derivatives.DerivativeMaker.upload_jp2_files')
    @patch('src.create_derivatives.DerivativeMaker.cleanup_successful')
    @patch('src.create_derivatives.DerivativeMaker.send_success_message')
    @patch('src.create_derivatives.DerivativeMaker.send_failure_message')
    def test_run_with_exception(self, mock_failure_message, mock_success_message, mock_cleanup,
                                mock_upload, mock_create, mock_stripped, mock_extract, mock_download, mock_data, mock_start_message):
        exception = Exception("foo")
        mock_data.side_effect = exception
        self.derivative_maker.run()
        mock_failure_message.assert_called_once_with(exception)
        mock_success_message.assert_not_called()
        mock_cleanup.assert_not_called()
        mock_upload.assert_not_called()
        mock_create.assert_not_called()
        mock_stripped.assert_not_called()
        mock_extract.assert_not_called()
        mock_download.assert_not_called()
        mock_start_message.assert_called_once_with()

    @mock_aws
    def test_download_package(self):
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket=self.derivative_maker.source_bucket)
        s3.put_object(
            Bucket=self.derivative_maker.source_bucket,
            Key=f'{self.derivative_maker.package_id}.tar.gz',
            Body=b'foo')
        download_path = self.derivative_maker.download_package(self.derivative_maker.package_id)
        self.assertTrue(download_path.is_file())

    # def test_extract_package(self):
    #     shutil.copy(
    #         Path('tests', 'fixtures', 'bags', f'{self.derivative_maker.package_id}.tar.gz'),
    #         self.derivative_maker.tmp_dir)
    #     extracted_path = self.derivative_maker.extract_package(
    #         Path(self.derivative_maker.tmp_dir, f'{self.derivative_maker.package_id}.tar.gz'))
    #     self.assertTrue(extracted_path.is_dir())
    #     self.assertEqual(
    #         extracted_path,
    #         Path(
    #             self.derivative_maker.tmp_dir,
    #             self.derivative_maker.package_id))

    def test_convert_to_stripped_tiff(self):
        Path(
            self.derivative_maker.tmp_dir,
            self.derivative_maker.package_id,
            'data',
            'service').mkdir(
            parents=True)
        shutil.copy(
            Path('tests', 'fixtures', 'tiff', 'file_example_TIFF_1MB_001.tif'),
            Path(self.derivative_maker.tmp_dir, self.derivative_maker.package_id, 'data', 'service'))
        self.derivative_maker.convert_to_stripped_tiff(
            Path(self.derivative_maker.tmp_dir, self.derivative_maker.package_id))
        self.assertTrue(
            Path(
                self.derivative_maker.tmp_dir,
                self.derivative_maker.package_id,
                'data',
                'service',
                'file_example_TIFF_1MB_001.tif'
            ).is_file())
        self.assertFalse(
            Path(
                self.derivative_maker.tmp_dir,
                self.derivative_maker.package_id,
                'data',
                'service',
                'file_example_TIFF_1MB_001__stripped.tif'
            ).is_file()
        )

    def test_get_page_number(self):
        for input, expected in [
                ("image/BbgfpzAC8AGr8DLokEzacp_0001_se", "0001"),
                ("image/BbgfpzAC8AGr8DLokEzacp_0001_m", "0001"),
                ("image/BbgfpzAC8AGr8DLokEzacp_001", "0001"),
                ("image/BbgfpzAC8AGr8DLokEzacp_1", "0001")
        ]:
            output = self.derivative_maker.get_page_number(input)
            self.assertEqual(output, expected)

    def test_calculate_layers(self):
        output = self.derivative_maker.calculate_layers(
            Path('tests', 'fixtures', 'tiff', 'file_example_TIFF_1MB_001.tif'))
        self.assertEqual(output, 4)

    @patch('src.create_derivatives.DerivativeMaker.get_page_number')
    @patch('src.create_derivatives.DerivativeMaker.calculate_layers')
    def test_create_jp2_files(self, mock_layers, mock_page):
        mock_layers.return_value = 4
        mock_page.return_value = '0001'
        dimes_id = '123456789'
        Path(
            self.derivative_maker.tmp_dir,
            self.derivative_maker.package_id,
            'data',
            'service').mkdir(
            parents=True)
        shutil.copy(
            Path('tests', 'fixtures', 'tiff', 'file_example_TIFF_1MB_001.tif'),
            Path(self.derivative_maker.tmp_dir, self.derivative_maker.package_id, 'data', 'service'))
        jp2_dir = self.derivative_maker.create_jp2_files(
            Path(self.derivative_maker.tmp_dir, self.derivative_maker.package_id), dimes_id)
        self.assertEqual(jp2_dir, Path(self.derivative_maker.tmp_dir, 'jp2'))
        self.assertTrue(Path(self.derivative_maker.tmp_dir, 'jp2', f'{dimes_id}_0001.jp2').is_file())

    @mock_aws
    def test_upload_jp2_files(self):
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket=self.derivative_maker.destination_bucket)
        self.derivative_maker.upload_jp2_files(Path('tests', 'fixtures', 'jp2'))
        uploaded_files = s3.list_objects_v2(Bucket=self.derivative_maker.destination_bucket)['Contents']
        uploaded_keys = [u['Key'] for u in uploaded_files]
        self.assertEqual(uploaded_keys,
                         ['images/sample.jp2',
                          'images/sample_2.jp2',
                          'images/sample_3.jp2',
                          'images/sample_4.jp2'])

    @mock_aws
    def test_cleanup_successful(self):
        package_key = f'{self.derivative_maker.package_id}.tar.gz'
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket=self.derivative_maker.source_bucket)
        s3.put_object(
            Bucket=self.derivative_maker.source_bucket,
            Key=package_key,
            Body=b'foo')
        self.derivative_maker.cleanup_successful(self.derivative_maker.package_id)
        with self.assertRaises(ClientError) as err:
            s3.head_object(
                Bucket=self.derivative_maker.source_bucket,
                Key=package_key)
        assert '404' in str(err.exception)

    def tearDown(self):
        shutil.rmtree(self.derivative_maker.tmp_dir)


class MessageTests(TestCase):

    def set_up_sns(self, sns):
        topic_arn = sns.create_topic(
            Name='my-topic.fifo',
            Attributes={
                "FifoTopic": "true",
                "ContentBasedDeduplication": "true"
            }
        )['TopicArn']
        sqs_conn = boto3.resource("sqs", region_name="us-east-1")
        queue_name = "test-queue.fifo"
        sqs_conn.create_queue(
            QueueName=queue_name,
            Attributes={
                "FifoQueue": "true",
                "ContentBasedDeduplication": "true"
            }
        )
        sns.subscribe(
            TopicArn=topic_arn,
            Protocol="sqs",
            Endpoint=f"arn:aws:sqs:us-east-1:{DEFAULT_ACCOUNT_ID}:{queue_name}",
        )
        return topic_arn, sqs_conn, queue_name

    @mock_aws
    @patch('src.create_derivatives.DerivativeMaker.get_client_with_role')
    def test_send_start_message(self, mock_role):
        """Asserts success messages are delivered as expected."""
        sns = boto3.client('sns', region_name='us-east-1')
        mock_role.return_value = sns
        topic_arn, sqs_conn, queue_name = self.set_up_sns(sns)

        derivative_maker = DerivativeMaker(*DEFAULT_ARGS)
        derivative_maker.sns_topic = topic_arn

        derivative_maker.send_start_message()

        queue = sqs_conn.get_queue_by_name(QueueName=queue_name)
        messages = queue.receive_messages(MaxNumberOfMessages=1)
        message_body = json.loads(messages[0].body)
        assert message_body['Message'] == 'IIIF derivative creation started.'
        assert message_body['MessageAttributes']['outcome']['Value'] == 'STARTED'
        assert message_body['MessageAttributes']['package_id']['Value'] == derivative_maker.package_id
        assert message_body['MessageAttributes']['service']['Value'] == derivative_maker.service_name
        assert message_body['MessageAttributes']['message']['Value'] == 'IIIF derivative creation started.'

    @mock_aws
    @patch('src.create_derivatives.DerivativeMaker.get_client_with_role')
    def test_send_success_message(self, mock_role):
        """Asserts success messages are delivered as expected."""
        sns = boto3.client('sns', region_name='us-east-1')
        mock_role.return_value = sns
        topic_arn, sqs_conn, queue_name = self.set_up_sns(sns)

        derivative_maker = DerivativeMaker(*DEFAULT_ARGS)
        derivative_maker.sns_topic = topic_arn

        package_data = {}
        derivative_maker.send_success_message(package_data)

        queue = sqs_conn.get_queue_by_name(QueueName=queue_name)
        messages = queue.receive_messages(MaxNumberOfMessages=1)
        message_body = json.loads(messages[0].body)
        assert message_body['Message'] == json.dumps(package_data)
        assert message_body['MessageAttributes']['outcome']['Value'] == 'SUCCESS'
        assert message_body['MessageAttributes']['package_id']['Value'] == derivative_maker.package_id
        assert message_body['MessageAttributes']['service']['Value'] == derivative_maker.service_name
        assert message_body['MessageAttributes']['message']['Value'] == 'IIIF derivatives created.'

    @mock_aws
    @patch('src.create_derivatives.DerivativeMaker.get_client_with_role')
    @patch('traceback.format_exception')
    def test_send_failure_message(self, mock_traceback, mock_role):
        """Asserts failure messages are delivered as expected."""
        sns = boto3.client('sns', region_name='us-east-1')
        mock_role.return_value = sns
        topic_arn, sqs_conn, queue_name = self.set_up_sns(sns)

        derivative_maker = DerivativeMaker(*DEFAULT_ARGS)
        derivative_maker.sns_topic = topic_arn
        exception_message = "foo"
        exception = Exception(exception_message)
        mock_traceback.return_value = ["baz", "buzz"]

        derivative_maker.send_failure_message(exception)

        queue = sqs_conn.get_queue_by_name(QueueName=queue_name)
        messages = queue.receive_messages(MaxNumberOfMessages=1)
        message_body = json.loads(messages[0].body)
        assert message_body['Message'] == "baz"
        assert message_body['MessageAttributes']['outcome']['Value'] == 'FAILURE'
        assert message_body['MessageAttributes']['package_id']['Value'] == derivative_maker.package_id
        assert exception_message in message_body['MessageAttributes']['message']['Value']
