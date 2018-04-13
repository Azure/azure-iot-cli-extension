import pytest
from knack.util import CLIError
from azext_iot.common.utility import validate_min_python_version
from azext_iot._validators import mode2_iot_login_handler


class TestMinPython():
    @pytest.mark.parametrize("pymajor, pyminor", [
        (3, 6),
        (3, 4),
        (2, 7)
    ])
    def test_min_python(self, mocker, pymajor, pyminor):
        version_mock = mocker.patch('azext_iot.common.utility.sys.version_info')
        version_mock.major = pymajor
        version_mock.minor = pyminor

        assert validate_min_python_version(2, 7)

    @pytest.mark.parametrize("pymajor, pyminor, exception", [
        (3, 6, SystemExit),
        (3, 4, SystemExit),
        (2, 7, SystemExit)
    ])
    def test_min_python_error(self, mocker, pymajor, pyminor, exception):
        version_mock = mocker.patch('azext_iot.common.utility.sys.version_info')
        version_mock.major = 2
        version_mock.minor = 6

        with pytest.raises(exception):
            validate_min_python_version(pymajor, pyminor)


class TestMode2Handler():
    @pytest.mark.parametrize("hub_name, dps_name, login", [
        ('myhub', '[]', None),
        ('[]', 'mydps', None),
        (None, None, 'mylogin'),
        ('myhub', '[]', 'mylogin'),
        ('[]', 'mydps', 'mylogin'),
        ('[]', '[]', '[]'),
        ('myhub', '[]', '[]'),
        ('[]', 'mydps', '[]'),
    ])
    def test_mode2_login(self, mocker, hub_name, dps_name, login):
        mock_cmd = mocker.MagicMock(name='mock cmd')
        mock_cmd.name = 'iot '
        mock_ns = mocker.MagicMock(name='mock ns')
        if login != '[]':
            mock_ns.login = login
        if hub_name != '[]':
            mock_ns.hub_name = hub_name
        if dps_name != '[]':
            mock_ns.dps_name = dps_name

        mode2_iot_login_handler(mock_cmd, mock_ns)

    @pytest.mark.parametrize("hub_name, dps_name, login", [
        (None, None, None)
    ])
    def test_mode2_login_error(self, mocker, hub_name, dps_name, login):
        mock_cmd = mocker.MagicMock(name='mock cmd')
        mock_cmd.name = 'iot '
        mock_ns = mocker.MagicMock(name='mock ns')
        if login != '[]':
            mock_ns.login = login
        if hub_name != '[]':
            mock_ns.hub_name = hub_name
        if dps_name != '[]':
            mock_ns.dps_name = dps_name

        with pytest.raises(CLIError):
            mode2_iot_login_handler(mock_cmd, mock_ns)
