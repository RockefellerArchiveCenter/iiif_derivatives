from requests import Session
from requests.exceptions import HTTPError


class ZodiacClientError(Exception):
    pass


class ZodiacClient(object):

    def __init__(self, baseurl):
        self.session = Session()
        self.session.headers.update({
            'Accept': 'application/json',
        })
        self.baseurl = baseurl.rstrip('/')

    def get(self, uri):
        """Makes an HTTP GET request"""
        url = f'{self.baseurl}/{uri.lstrip("/")}'
        try:
            resp = self.session.get(url)
            resp.raise_for_status()
            return resp.json()
        except HTTPError:
            raise ZodiacClientError(f"Error fetching url {url}: {resp.status_code} {resp.text}")
