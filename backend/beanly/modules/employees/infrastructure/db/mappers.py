from beanly.modules.employees.domain.entities import Employee
from beanly.modules.employees.domain.enums import EmployeeStatus
from beanly.modules.employees.infrastructure.db.models import EmployeeModel


def to_employee(model: EmployeeModel, location_ids: tuple) -> Employee:
    return Employee(
        id=model.id,
        organization_id=model.organization_id,
        user_id=model.user_id,
        first_name=model.first_name,
        last_name=model.last_name,
        phone=model.phone,
        position=model.position,
        status=EmployeeStatus(model.status),
        location_ids=location_ids,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
