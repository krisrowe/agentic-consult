from setuptools import setup, find_packages

setup(
    name="agentic-consult",
    version="0.0.3",
    description="Email scan + TickTick refresh tooling",
    packages=find_packages(exclude=("tests", "tests.*")),
    include_package_data=True,
    install_requires=[
        "click>=8.0",
        "pyyaml>=6.0",
        "google-genai",
        "jsonschema",
        "google-api-python-client",
        "google-auth",
        "mcp>=1.0.0",
        "pathspec",
        "google-workspace-access",  # gwsa SDK for email operations
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "jsonschema>=4.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "consult=agentic_consult.cli.main:main",
            "consult-mcp=agentic_consult.mcp.server:run_server",
        ],
    },
    python_requires=">=3.10",
)
