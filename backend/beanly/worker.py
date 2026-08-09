from celery import Celery

from beanly.core.config.settings import get_settings

settings = get_settings()
app = Celery("beanly", broker=settings.celery_broker_url)
