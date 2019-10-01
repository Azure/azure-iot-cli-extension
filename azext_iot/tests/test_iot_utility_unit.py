import pytest
from knack.util import CLIError
from azext_iot.common.utility import validate_min_python_version
from azext_iot.common.deps import ensure_uamqp
from azext_iot._validators import mode2_iot_login_handler
from azext_iot.constants import EVENT_LIB


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


class TestEnsureUamqp():
    @pytest.fixture()
    def uamqp_scenario(self, mocker):
        get_uamqp = mocker.patch('azext_iot.common.deps.get_uamqp_ext_version')
        update_uamqp = mocker.patch('azext_iot.common.deps.update_uamqp_ext_version')
        installer = mocker.patch('azext_iot.common.deps.install')
        installer.return_value = True
        get_uamqp.return_value = EVENT_LIB[1]
        test_import = mocker.patch('azext_iot.common.deps.test_import')
        test_import.return_value = True
        m_exit = mocker.patch('azext_iot.common.deps.sys.exit')

        return {'get_uamqp': get_uamqp, 'update_uamqp': update_uamqp,
                'installer': installer, 'test_import': test_import, 'exit': m_exit}

    @pytest.mark.parametrize("case, extra_input, external_input", [
        ('importerror', None, 'y'),
        ('importerror', None, 'n'),
        ('importerror', 'yes;', None),
        ('compatibility', None, 'y'),
        ('compatibility', None, 'n'),
        ('compatibility', 'yes;', None),
        ('repair', 'repair;', 'y'),
        ('repair', 'repair;yes;', None),
        ('repair', 'repair;', 'n')
    ])
    def test_ensure_uamqp_version(self, mocker, uamqp_scenario,
                                  case, extra_input, external_input):
        if case == 'importerror':
            uamqp_scenario['test_import'].return_value = False
        elif case == 'compatibility':
            uamqp_scenario['get_uamqp'].return_value = '0.0.0'

        from functools import partial
        kwargs = {}
        user_cancelled = True
        if extra_input and 'yes;' in extra_input:
            kwargs['yes'] = True
            user_cancelled = False
        if extra_input and 'repair;' in extra_input:
            kwargs['repair'] = True
        if external_input:
            mocked_input = mocker.patch('azext_iot.common.deps.input')
            mocked_input.return_value = external_input
            if external_input.lower() == 'y':
                user_cancelled = False

        method = partial(ensure_uamqp, mocker.MagicMock(), **kwargs)
        method()

        if user_cancelled:
            assert uamqp_scenario['exit'].call_args
        else:
            install_args = uamqp_scenario['installer'].call_args
            assert install_args[0][0] == EVENT_LIB[0]
            assert install_args[1]['custom_version'] == '>={},<{}'.format(EVENT_LIB[1], EVENT_LIB[2])
