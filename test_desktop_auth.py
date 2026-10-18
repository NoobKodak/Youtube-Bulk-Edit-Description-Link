"""Verify the desktop keeps the system-browser OAuth handoff without signing in."""
import unittest
from unittest.mock import Mock,patch
import main

class DesktopAuthTests(unittest.TestCase):
    def test_system_browser_loopback_flow_is_preserved(self):
        creds=Mock();creds.to_json.return_value='{}'
        flow=Mock();flow.run_local_server.return_value=creds
        with patch.object(main.os.path,'exists',side_effect=lambda p:p==main.CLIENT_SECRET_FILE), patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file',return_value=flow), patch.object(main,'atomic_write_json') as write, patch('googleapiclient.discovery.build',return_value='mock-service'):
            self.assertEqual(main.build_service(),'mock-service')
            flow.run_local_server.assert_called_once_with(port=0,access_type='offline',prompt='consent')
            write.assert_called_once_with(main.TOKEN_FILE,{})

if __name__=='__main__':unittest.main()
