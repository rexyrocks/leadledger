import pytest
from conftest import backend_choice


@pytest.mark.parametrize('platform',['win32','darwin','linux'])
def test_explicit_server_never_selects_redislite(platform):
    assert backend_choice('server',platform)=='server'


def test_windows_auto_does_not_import_embedded_runtime():
    assert backend_choice('auto','win32')=='unavailable'
    assert backend_choice('embedded','win32')=='unavailable'


@pytest.mark.parametrize('platform',['darwin','linux'])
def test_supported_auto_uses_embedded(platform):
    assert backend_choice('auto',platform)=='embedded'


def test_invalid_backend_is_configuration_error():
    with pytest.raises(ValueError): backend_choice('sqlite','win32')
