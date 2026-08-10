from beanly.modules.integrations.application.ports import (
    DeliveryProvider,
    FiscalProvider,
    NotificationProvider,
    PaymentProvider,
)

type ProviderAdapter = (
    PaymentProvider | FiscalProvider | DeliveryProvider | NotificationProvider
)
