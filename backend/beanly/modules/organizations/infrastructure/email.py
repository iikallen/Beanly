import logging

from beanly.modules.organizations.domain.enums import MembershipRole

logger = logging.getLogger(__name__)


class ConsoleEmailSender:
    async def send_invitation(
        self, email: str, organization_name: str, role: MembershipRole, invite_url: str
    ) -> None:
        logger.info(
            "INVITATION: email=%s organization=%s role=%s url=%s",
            email,
            organization_name,
            role.value,
            invite_url,
        )
