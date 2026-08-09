class InventoryError(Exception):
    pass


class InventoryNotFound(InventoryError):
    pass


class InvalidInventoryOperation(InventoryError):
    pass


class InvalidInventoryUnit(InventoryError):
    pass


class IdempotencyConflict(InventoryError):
    pass


class DuplicateInventoryResource(InventoryError):
    pass
