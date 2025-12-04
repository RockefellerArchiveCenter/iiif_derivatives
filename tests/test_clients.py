from unittest import TestCase
from unittest.mock import patch

from requests import Session as RequestsSession
from requests.exceptions import HTTPError

from src.clients import ZodiacClient


class ZodiacClientTests(TestCase):

    def setUp(self):
        self.baseurl = 'https://example.com'
        self.client = ZodiacClient(self.baseurl)

    def test_init(self):
        """Asserts attributes are correctly set on init"""
        self.assertIsInstance(self.client.session, RequestsSession)
        self.assertEqual(self.client.session.headers.get('Accept'), 'application/json')
        self.assertEqual(self.client.baseurl, self.baseurl)

    @patch('requests.Session.get')
    def test_get(self, mock_get):
        """Assert get requests and exceptions are handled as expected"""
        data = {}
        mock_get.return_value.json.return_value = data
        mock_get.return_value.raise_for_status.return_value = None
        package_uri = 'packages/12345'
        output = self.client.get(package_uri)
        self.assertEqual(output, data)
        mock_get.assert_called_once_with(f'{self.baseurl}/{package_uri}')

        mock_get.return_value.raise_for_status.side_effect = HTTPError('foo')
        with self.assertRaises(Exception) as err:
            self.client.get(package_uri)
        self.assertTrue(str(err.exception).startswith(
            'Error fetching url https://example.com/packages/12345'))
