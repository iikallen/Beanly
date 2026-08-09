class MenuError(Exception):
    pass


class MenuNotFound(MenuError):
    pass


class MenuConflict(MenuError):
    pass


class InvalidMenuOperation(MenuError):
    pass
