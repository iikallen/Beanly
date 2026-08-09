class DuplicateEmailError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidSessionError(Exception):
    pass


class AuthenticationRequiredError(Exception):
    pass
