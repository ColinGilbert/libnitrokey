import pytest
import cffi
from enum import Enum

ffi = cffi.FFI()
gs = ffi.string


def to_hex(s):
    return "".join("{:02x}".format(ord(c)) for c in s)


RFC_SECRET_HR = '12345678901234567890'
RFC_SECRET = to_hex(RFC_SECRET_HR)  # '12345678901234567890'


# print( repr((RFC_SECRET, RFC_SECRET_, len(RFC_SECRET))) )

class DefaultPasswords(Enum):
    ADMIN = '12345678'
    USER = '123456'
    ADMIN_TEMP = '123123123'
    USER_TEMP = '234234234'


class DeviceErrorCode(Enum):
    STATUS_OK = 0
    NOT_PROGRAMMED = 3
    WRONG_PASSWORD = 4
    STATUS_NOT_AUTHORIZED = 5
    STATUS_AES_DEC_FAILED = 0xa


class LibraryErrors(Enum):
    TOO_LONG_STRING = 200
    INVALID_SLOT = 201
    INVALID_HEX_STRING = 202
    TARGET_BUFFER_SIZE_SMALLER_THAN_SOURCE = 203


@pytest.fixture(scope="module")
def C(request):
    fp = '../NK_C_API.h'

    declarations = []
    with open(fp, 'r') as f:
        declarations = f.readlines()

    a = iter(declarations)
    for declaration in a:
        if declaration.startswith('extern') and not '"C"' in declaration:
            declaration = declaration.replace('extern', '').strip()
            while not ';' in declaration:
                declaration += (next(a)).strip()
            print(declaration)
            ffi.cdef(declaration)

    C = ffi.dlopen("../build/libnitrokey.so")
    C.NK_set_debug(False)
    nk_login = C.NK_login_auto()
    if nk_login != 1:
        print('No devices detected!')
    assert nk_login == 1  # returns 0 if not connected or wrong model or 1 when connected

    # assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    # assert C.NK_user_authenticate(DefaultPasswords.USER, DefaultPasswords.USER_TEMP) == DeviceErrorCode.STATUS_OK

    # C.NK_status()

    def fin():
        print('\nFinishing connection to device')
        C.NK_logout()
        print('Finished')

    request.addfinalizer(fin)
    C.NK_set_debug(True)

    return C


def test_enable_password_safe(C):
    assert C.NK_lock_device() == DeviceErrorCode.STATUS_OK
    assert C.NK_enable_password_safe('wrong_password') == DeviceErrorCode.WRONG_PASSWORD
    assert C.NK_enable_password_safe(DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK


def test_write_password_safe_slot(C):
    assert C.NK_lock_device() == DeviceErrorCode.STATUS_OK
    assert C.NK_write_password_safe_slot(0, 'slotname1', 'login1', 'pass1') == DeviceErrorCode.STATUS_NOT_AUTHORIZED
    assert C.NK_enable_password_safe(DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_password_safe_slot(0, 'slotname1', 'login1', 'pass1') == DeviceErrorCode.STATUS_OK


def test_get_password_safe_slot_name(C):
    assert C.NK_enable_password_safe(DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_password_safe_slot(0, 'slotname1', 'login1', 'pass1') == DeviceErrorCode.STATUS_OK
    assert C.NK_lock_device() == DeviceErrorCode.STATUS_OK
    assert gs(C.NK_get_password_safe_slot_name(0)) == ''
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_NOT_AUTHORIZED

    assert C.NK_enable_password_safe(DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK
    assert gs(C.NK_get_password_safe_slot_name(0)) == 'slotname1'
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK


def test_get_password_safe_slot_login_password(C):
    assert C.NK_enable_password_safe(DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_password_safe_slot(0, 'slotname1', 'login1', 'pass1') == DeviceErrorCode.STATUS_OK
    slot_login = C.NK_get_password_safe_slot_login(0)
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK
    assert gs(slot_login) == 'login1'
    slot_password = gs(C.NK_get_password_safe_slot_password(0))
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK
    assert slot_password == 'pass1'


def test_erase_password_safe_slot(C):
    assert C.NK_enable_password_safe(DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK
    assert C.NK_erase_password_safe_slot(0) == DeviceErrorCode.STATUS_OK
    assert gs(C.NK_get_password_safe_slot_name(0)) == ''
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK  # TODO CHECK shouldn't this be DeviceErrorCode.NOT_PROGRAMMED ?


def test_password_safe_slot_status(C):
    C.NK_set_debug(True)
    assert C.NK_enable_password_safe(DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK
    assert C.NK_erase_password_safe_slot(0) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_password_safe_slot(1, 'slotname2', 'login2', 'pass2') == DeviceErrorCode.STATUS_OK
    safe_slot_status = C.NK_get_password_safe_slot_status()
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK
    is_slot_programmed = list(ffi.cast("uint8_t [16]", safe_slot_status)[0:16])
    print((is_slot_programmed, len(is_slot_programmed)))
    assert is_slot_programmed[0] == 0
    assert is_slot_programmed[1] == 1


@pytest.mark.xfail(run=False, reason="issue to register: device locks up "
                                     "after below commands sequence (reinsertion fixes), skipping for now")
def test_issue_device_locks_on_second_key_generation_in_sequence(C):
    assert C.NK_build_aes_key(DefaultPasswords.ADMIN) == DeviceErrorCode.STATUS_OK
    assert C.NK_build_aes_key(DefaultPasswords.ADMIN) == DeviceErrorCode.STATUS_OK


def test_regenerate_aes_key(C):
    C.NK_set_debug(True)
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_build_aes_key(DefaultPasswords.ADMIN) == DeviceErrorCode.STATUS_OK
    assert C.NK_enable_password_safe(DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK


@pytest.mark.xfail(reason="firmware bug: regenerating AES key command not always results in cleared slot data")
def test_destroy_password_safe(C):
    """
    Sometimes fails on NK Pro - slot name is not cleared ergo key generation has not succeed despite the success result
    returned from the device
    """
    C.NK_set_debug(True)
    assert C.NK_enable_password_safe(DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK
    # write password safe slot
    assert C.NK_write_password_safe_slot(0, 'slotname1', 'login1', 'pass1') == DeviceErrorCode.STATUS_OK
    # read slot
    assert gs(C.NK_get_password_safe_slot_name(0)) == 'slotname1'
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK
    slot_login = C.NK_get_password_safe_slot_login(0)
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK
    assert gs(slot_login) == 'login1'
    # destroy password safe by regenerating aes key
    assert C.NK_lock_device() == DeviceErrorCode.STATUS_OK

    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_build_aes_key(DefaultPasswords.ADMIN) == DeviceErrorCode.STATUS_OK
    assert C.NK_enable_password_safe(DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK

    assert gs(C.NK_get_password_safe_slot_name(0)) != 'slotname1'
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK

    # check was slot status cleared
    safe_slot_status = C.NK_get_password_safe_slot_status()
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK
    is_slot_programmed = list(ffi.cast("uint8_t [16]", safe_slot_status)[0:16])
    assert is_slot_programmed[0] == 0


def test_is_AES_supported(C):
    assert C.NK_is_AES_supported('wrong password') != 1
    assert C.NK_get_last_command_status() == DeviceErrorCode.WRONG_PASSWORD
    assert C.NK_is_AES_supported(DefaultPasswords.USER) == 1
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK


def test_admin_PIN_change(C):
    new_password = '123123123'
    assert C.NK_change_admin_PIN('wrong_password', new_password) == DeviceErrorCode.WRONG_PASSWORD
    assert C.NK_change_admin_PIN(DefaultPasswords.ADMIN, new_password) == DeviceErrorCode.STATUS_OK
    assert C.NK_change_admin_PIN(new_password, DefaultPasswords.ADMIN) == DeviceErrorCode.STATUS_OK


def test_user_PIN_change(C):
    new_password = '123123123'
    assert C.NK_change_user_PIN('wrong_password', new_password) == DeviceErrorCode.WRONG_PASSWORD
    assert C.NK_change_user_PIN(DefaultPasswords.USER, new_password) == DeviceErrorCode.STATUS_OK
    assert C.NK_change_user_PIN(new_password, DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK


def test_too_long_strings(C):
    new_password = '123123123'
    long_string = 'a' * 100
    assert C.NK_change_user_PIN(long_string, new_password) == LibraryErrors.TOO_LONG_STRING
    assert C.NK_change_user_PIN(new_password, long_string) == LibraryErrors.TOO_LONG_STRING
    assert C.NK_change_admin_PIN(long_string, new_password) == LibraryErrors.TOO_LONG_STRING
    assert C.NK_change_admin_PIN(new_password, long_string) == LibraryErrors.TOO_LONG_STRING
    assert C.NK_first_authenticate(long_string, DefaultPasswords.ADMIN_TEMP) == LibraryErrors.TOO_LONG_STRING
    assert C.NK_erase_totp_slot(0, long_string) == LibraryErrors.TOO_LONG_STRING
    digits = False
    assert C.NK_write_hotp_slot(1, long_string, RFC_SECRET, 0, digits, False, False, "",
                                DefaultPasswords.ADMIN_TEMP) == LibraryErrors.TOO_LONG_STRING
    assert C.NK_write_hotp_slot(1, 'long_test', RFC_SECRET, 0, digits, False, False, "",
                                long_string) == LibraryErrors.TOO_LONG_STRING
    assert C.NK_get_hotp_code_PIN(0, long_string) == 0
    assert C.NK_get_last_command_status() == LibraryErrors.TOO_LONG_STRING


def test_invalid_slot(C):
    invalid_slot = 255
    assert C.NK_erase_totp_slot(invalid_slot, 'some password') == LibraryErrors.INVALID_SLOT
    assert C.NK_write_hotp_slot(invalid_slot, 'long_test', RFC_SECRET, 0, False, False, False, "",
                                'aaa') == LibraryErrors.INVALID_SLOT
    assert C.NK_get_hotp_code_PIN(invalid_slot, 'some password') == 0
    assert C.NK_get_last_command_status() == LibraryErrors.INVALID_SLOT
    assert C.NK_erase_password_safe_slot(invalid_slot) == LibraryErrors.INVALID_SLOT
    assert C.NK_enable_password_safe(DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK
    assert gs(C.NK_get_password_safe_slot_name(invalid_slot)) == ''
    assert C.NK_get_last_command_status() == LibraryErrors.INVALID_SLOT
    assert gs(C.NK_get_password_safe_slot_login(invalid_slot)) == ''
    assert C.NK_get_last_command_status() == LibraryErrors.INVALID_SLOT


def test_admin_retry_counts(C):
    default_admin_retry_count = 3
    assert C.NK_get_admin_retry_count() == default_admin_retry_count
    assert C.NK_change_admin_PIN('wrong_password', DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.WRONG_PASSWORD
    assert C.NK_get_admin_retry_count() == default_admin_retry_count - 1
    assert C.NK_change_admin_PIN(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN) == DeviceErrorCode.STATUS_OK
    assert C.NK_get_admin_retry_count() == default_admin_retry_count


def test_user_retry_counts(C):
    default_user_retry_count = 3
    assert C.NK_get_user_retry_count() == default_user_retry_count
    assert C.NK_enable_password_safe('wrong_password') == DeviceErrorCode.WRONG_PASSWORD
    assert C.NK_get_user_retry_count() == default_user_retry_count - 1
    assert C.NK_enable_password_safe(DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK
    assert C.NK_get_user_retry_count() == default_user_retry_count


def test_unlock_user_password(C):
    C.NK_set_debug(True)
    default_user_retry_count = 3
    default_admin_retry_count = 3
    new_password = '123123123'
    assert C.NK_get_user_retry_count() == default_user_retry_count
    assert C.NK_change_user_PIN('wrong_password', new_password) == DeviceErrorCode.WRONG_PASSWORD
    assert C.NK_change_user_PIN('wrong_password', new_password) == DeviceErrorCode.WRONG_PASSWORD
    assert C.NK_change_user_PIN('wrong_password', new_password) == DeviceErrorCode.WRONG_PASSWORD
    assert C.NK_get_user_retry_count() == default_user_retry_count - 3
    assert C.NK_get_admin_retry_count() == default_admin_retry_count

    assert C.NK_unlock_user_password('wrong password', DefaultPasswords.USER) == DeviceErrorCode.WRONG_PASSWORD
    assert C.NK_get_admin_retry_count() == default_admin_retry_count - 1
    assert C.NK_unlock_user_password(DefaultPasswords.ADMIN, DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK
    assert C.NK_get_user_retry_count() == default_user_retry_count
    assert C.NK_get_admin_retry_count() == default_admin_retry_count


def test_admin_auth(C):
    assert C.NK_first_authenticate('wrong_password', DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.WRONG_PASSWORD
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK


def test_user_auth(C):
    assert C.NK_user_authenticate('wrong_password', DefaultPasswords.USER_TEMP) == DeviceErrorCode.WRONG_PASSWORD
    assert C.NK_user_authenticate(DefaultPasswords.USER, DefaultPasswords.USER_TEMP) == DeviceErrorCode.STATUS_OK


def check_HOTP_RFC_codes(C, func, prep=None, use_8_digits=False):
    """
    # https://tools.ietf.org/html/rfc4226#page-32
    """
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_hotp_slot(1, 'python_test', RFC_SECRET, 0, use_8_digits, False, False, "",
                                DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    test_data = [
        1284755224, 1094287082, 137359152, 1726969429, 1640338314, 868254676, 1918287922, 82162583, 673399871,
        645520489,
    ]
    for code in test_data:
        if prep:
            prep()
        r = func(1)
        code = str(code)[-8:] if use_8_digits else str(code)[-6:]
        assert int(code) == r


@pytest.mark.parametrize("use_8_digits", [False, True, ])
@pytest.mark.parametrize("use_pin_protection", [False, True, ])
def test_HOTP_RFC_use8digits_usepin(C, use_8_digits, use_pin_protection):
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_config(255, 255, 255, use_pin_protection, not use_pin_protection,
                             DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    if use_pin_protection:
        check_HOTP_RFC_codes(C,
                             lambda x: C.NK_get_hotp_code_PIN(x, DefaultPasswords.USER_TEMP),
                             lambda: C.NK_user_authenticate(DefaultPasswords.USER, DefaultPasswords.USER_TEMP),
                             use_8_digits=use_8_digits)
    else:
        check_HOTP_RFC_codes(C, C.NK_get_hotp_code, use_8_digits=use_8_digits)


def test_HOTP_token(C):
    """
    Check HOTP routine with written token ID to slot.
    """
    use_pin_protection = False
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_config(255, 255, 255, use_pin_protection, not use_pin_protection,
                             DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    token_ID = "AAV100000022"
    assert C.NK_write_hotp_slot(1, 'python_test', RFC_SECRET, 0, False, False, True, token_ID,
                                DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    for i in range(5):
        hotp_code = C.NK_get_hotp_code(1)
        assert hotp_code != 0
        assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK


@pytest.mark.xfail(reason="firmware bug: set time command not always changes the time on stick thus failing this test, "
                          "this does not influence normal use since setting time is not done every TOTP code request")
@pytest.mark.parametrize("PIN_protection", [False, True, ])
def test_TOTP_RFC_usepin(C, PIN_protection):
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_config(255, 255, 255, PIN_protection, not PIN_protection,
                             DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    # test according to https://tools.ietf.org/html/rfc6238#appendix-B
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_totp_slot(1, 'python_test', RFC_SECRET, 30, True, False, False, "",
                                DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK

    get_func = None
    if PIN_protection:
        get_func = lambda x, y, z, r: C.NK_get_totp_code_PIN(x, y, z, r, DefaultPasswords.USER_TEMP)
    else:
        get_func = C.NK_get_totp_code

    test_data = [
        (59, 1, 94287082),
        (1111111109, 0x00000000023523EC, 7081804),
        (1111111111, 0x00000000023523ED, 14050471),
        (1234567890, 0x000000000273EF07, 89005924),
    ]
    for t, T, code in test_data:
        """
        FIXME without the delay 50% of tests fails, with it only 12%, higher delay removes fails
        -> set_time function not always works, to investigate why
        """
        # import time
        # time.sleep(2)
        if PIN_protection:
            C.NK_user_authenticate(DefaultPasswords.USER, DefaultPasswords.USER_TEMP)
        assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
        assert C.NK_totp_set_time(t) == DeviceErrorCode.STATUS_OK
        r = get_func(1, T, 0, 30)  # FIXME T is not changing the outcome
        assert code == r


def test_get_slot_names(C):
    C.NK_set_debug(True)
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_erase_totp_slot(0, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    # erasing slot invalidates temporary password, so requesting authentication
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_erase_hotp_slot(0, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK

    for i in range(15):
        name = ffi.string(C.NK_get_totp_slot_name(i))
        if name == '':
            assert C.NK_get_last_command_status() == DeviceErrorCode.NOT_PROGRAMMED
    for i in range(3):
        name = ffi.string(C.NK_get_hotp_slot_name(i))
        if name == '':
            assert C.NK_get_last_command_status() == DeviceErrorCode.NOT_PROGRAMMED


def test_get_OTP_codes(C):
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_config(255, 255, 255, False, True, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    for i in range(15):
        code = C.NK_get_totp_code(i, 0, 0, 0)
        if code == 0:
            assert C.NK_get_last_command_status() == DeviceErrorCode.NOT_PROGRAMMED

    for i in range(3):
        code = C.NK_get_hotp_code(i)
        if code == 0:
            assert C.NK_get_last_command_status() == DeviceErrorCode.NOT_PROGRAMMED


def test_get_OTP_code_from_not_programmed_slot(C):
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_config(255, 255, 255, False, True, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_erase_hotp_slot(0, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_erase_totp_slot(0, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK

    code = C.NK_get_hotp_code(0)
    assert code == 0
    assert C.NK_get_last_command_status() == DeviceErrorCode.NOT_PROGRAMMED

    code = C.NK_get_totp_code(0, 0, 0, 0)
    assert code == 0
    assert C.NK_get_last_command_status() == DeviceErrorCode.NOT_PROGRAMMED


def test_get_code_user_authorize(C):
    C.NK_set_debug(True)
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_totp_slot(0, 'python_otp_auth', RFC_SECRET, 30, True, False, False, "",
                                DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    # enable PIN protection of OTP codes with write_config
    # TODO create convinience function on C API side to enable/disable OTP USER_PIN protection
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_config(255, 255, 255, True, False, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    code = C.NK_get_totp_code(0, 0, 0, 0)
    assert code == 0
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_NOT_AUTHORIZED
    # disable PIN protection with write_config
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_config(255, 255, 255, False, True, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    code = C.NK_get_totp_code(0, 0, 0, 0)
    assert code != 0
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK


def cast_pointer_to_tuple(obj, typen, len):
    # usage:
    #     config = cast_pointer_to_tuple(config_raw_data, 'uint8_t', 5)
    return tuple(ffi.cast("%s [%d]" % (typen, len), obj)[0:len])


def test_read_write_config(C):
    C.NK_set_debug(True)

    # let's set sample config with pin protection and disabled scrolllock
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_config(0, 1, 2, True, False, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    config_raw_data = C.NK_read_config()
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK
    config = cast_pointer_to_tuple(config_raw_data, 'uint8_t', 5)
    assert config == (0, 1, 2, True, False)

    # restore defaults and check
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_config(255, 255, 255, False, True, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    config_raw_data = C.NK_read_config()
    assert C.NK_get_last_command_status() == DeviceErrorCode.STATUS_OK
    config = cast_pointer_to_tuple(config_raw_data, 'uint8_t', 5)
    assert config == (255, 255, 255, False, True)


def wait(t):
    import time
    msg = 'Waiting for %d seconds' % t
    print(msg.center(40, '='))
    time.sleep(t)


def test_factory_reset(C):
    C.NK_set_debug(True)
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_config(255, 255, 255, False, True, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_write_hotp_slot(1, 'python_test', RFC_SECRET, 0, False, False, False, "",
                                DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_get_hotp_code(1) == 755224
    assert C.NK_factory_reset(DefaultPasswords.ADMIN) == DeviceErrorCode.STATUS_OK
    wait(10)
    assert C.NK_get_hotp_code(1) != 287082
    assert C.NK_get_last_command_status() == DeviceErrorCode.NOT_PROGRAMMED
    # restore AES key
    assert C.NK_first_authenticate(DefaultPasswords.ADMIN, DefaultPasswords.ADMIN_TEMP) == DeviceErrorCode.STATUS_OK
    assert C.NK_build_aes_key(DefaultPasswords.ADMIN) == DeviceErrorCode.STATUS_OK
    assert C.NK_enable_password_safe(DefaultPasswords.USER) == DeviceErrorCode.STATUS_OK
    assert C.NK_lock_device() == DeviceErrorCode.STATUS_OK


@pytest.mark.skip(reason='Experimental')
def test_clear(C):
    d = 'asdasdasd'
    print(d)
    C.clear_password(d)
    print(d)


def test_get_status(C):
    status = C.NK_status()
    s = gs(status)
    assert len(s) > 0


def test_get_serial_number(C):
    sn = C.NK_device_serial_number()
    sn = gs(sn)
    assert len(sn) > 0
    print(('Serial number of the device: ', sn))


@pytest.mark.parametrize("invalid_hex_string",
                         ['text', '00  ', '0xff', 'zzzzzzzzzzzz', 'fff', '', 'f' * 257, 'f' * 258])
def test_invalid_secret_hex_string_for_OTP_write(C, invalid_hex_string):
    """
    Tests for invalid secret hex string during writing to OTP slot. Invalid strings are not hexadecimal number,
    empty or longer than 255 characters.
    """
    assert C.NK_write_hotp_slot(1, 'slot_name', invalid_hex_string, 0, True, False, False, '',
                                DefaultPasswords.ADMIN_TEMP) == LibraryErrors.INVALID_HEX_STRING
    assert C.NK_write_totp_slot(1, 'python_test', invalid_hex_string, 30, True, False, False, "",
                                DefaultPasswords.ADMIN_TEMP) == LibraryErrors.INVALID_HEX_STRING


def test_warning_binary_bigger_than_secret_buffer(C):
    invalid_hex_string = to_hex('1234567890') * 3
    assert C.NK_write_hotp_slot(1, 'slot_name', invalid_hex_string, 0, True, False, False, '',
                                DefaultPasswords.ADMIN_TEMP) == LibraryErrors.TARGET_BUFFER_SIZE_SMALLER_THAN_SOURCE
