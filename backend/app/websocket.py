import logging

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("aerohub.websocket")


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        stale: list[WebSocket] = []
        for connection in tuple(self.active_connections):
            try:
                await connection.send_json(message)
            except (WebSocketDisconnect, RuntimeError, OSError):
                stale.append(connection)
            except Exception:
                logger.exception("Could not send a WebSocket update.")
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)


manager = ConnectionManager()
