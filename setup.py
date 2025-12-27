from setuptools import setup, find_packages

setup(
    name="agentic-consult",
    version="0.0.1",
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
        ],
    },
    python_requires=">=3.8",
)
