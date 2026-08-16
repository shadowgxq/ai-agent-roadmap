class MCPAdapter:
    def __init__(self, server_name: str, session: object) -> None:
        self.server_name = server_name
        self.session = session

    def public_name(self, remote_name: str) -> str:
        return f"{self.server_name}__{remote_name}"

    async def call(self, remote_name: str, arguments: dict[str, object]) -> object:
        return await self.session.call_tool(remote_name, arguments)
