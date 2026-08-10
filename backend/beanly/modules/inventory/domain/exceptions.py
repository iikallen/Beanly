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


class InventoryCountChanged(InvalidInventoryOperation):
    def __init__(self, changed_items: list[dict[str, str]]) -> None:
        super().__init__("Stock changed while inventory was being counted")
        self.changed_items = changed_items


class SourceControlledTransaction(InvalidInventoryOperation):
    pass
