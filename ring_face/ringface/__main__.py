import json
import logging
import os
import signal
from waitress import create_server
from .settings import Settings
from .store import Store
from .engine import Engine
from .service import Service
from .mqtt import Broker
from .web import create_app


class JsonFormatter(logging.Formatter):
    def format(self, record):
        try:
            item = json.loads(record.getMessage())
        except (ValueError, TypeError):
            item = {"message": record.getMessage()}
        if not isinstance(item,dict):
            item = {"message": str(item)}
        item.update(level=record.levelname, timestamp=self.formatTime(record))
        if record.exc_info:
            item["exception_type"] = record.exc_info[0].__name__
        return json.dumps(item)


def main():
    os.umask(0o077)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO,handlers=[handler])
    settings = Settings.load()
    store = Store(settings.data)
    engine = Engine(settings)
    service = Service(settings,store,engine)
    broker = Broker(settings,service)
    service.start()
    broker.start()
    server = create_server(create_app(settings,store,engine,service),host="0.0.0.0",port=8099,threads=2,
                           connection_limit=16,channel_timeout=30,max_request_body_size=32*1024*1024)
    def stop(*args):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    try:
        logging.info(json.dumps({"event":"started","inference":"lazy","threads":settings.opencv_threads}))
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        service.close()
        broker.close()
        engine.close()
        store.close()


if __name__ == "__main__":
    main()
