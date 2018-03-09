import pytest
from azext_iot.common.utility import validate_min_python_version


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
