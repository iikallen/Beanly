class OrganizationError(Exception):
    pass


class OrganizationNotFound(OrganizationError):
    pass


class MembershipNotFound(OrganizationError):
    pass


class LocationNotFound(OrganizationError):
    pass


class InvalidTimezone(OrganizationError, ValueError):
    pass


class OrganizationAccessDenied(OrganizationError):
    pass


class DuplicateMembership(OrganizationError):
    pass


class PermissionDenied(OrganizationError):
    pass


class CurrencyLocked(OrganizationError):
    pass


class InvalidLocationAccess(OrganizationError):
    pass


class InvitationNotFound(OrganizationError):
    pass


class InvitationGone(OrganizationError):
    pass


class InvitationAlreadyAccepted(OrganizationError):
    pass


class DuplicateInvitation(OrganizationError):
    pass


class InvitationEmailMismatch(OrganizationError):
    pass


class InvalidRoleAssignment(OrganizationError):
    pass
