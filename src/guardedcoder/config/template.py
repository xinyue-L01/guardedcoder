DEFAULT_CONFIG_TOML = """\
config_schema_version = "1"
read_paths = ["src"]
write_paths = ["src"]
verify_profiles = ["pytest"]
max_steps = 10
max_total_seconds = 300
command_timeout_seconds = 60
max_output_bytes = 65536
max_patch_bytes = 1000000
allow_delete = false
allow_network = false

[provider]
provider_id = "openai-compat"
base_url = "http://127.0.0.1:8080/v1"
model = "local"
timeout_seconds = 30

[[profiles]]
profile_id = "pytest"
argv_template = ["pytest", "--junitxml", "{junit_out}"]
cwd = "."
timeout_seconds = 60
max_output_bytes = 65536
"""
