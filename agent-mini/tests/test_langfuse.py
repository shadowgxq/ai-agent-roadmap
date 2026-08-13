from dotenv import load_dotenv
from langfuse import get_client

load_dotenv()

langfuse = get_client()

print("auth:", langfuse.auth_check())

with langfuse.start_as_current_observation(
    as_type="span",
    name="w09-smoke-test",
    input={"message": "hello langfuse"},
) as span:
    span.update(output={"status": "ok"})

langfuse.flush()
