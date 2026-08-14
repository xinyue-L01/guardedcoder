# Third-party licenses / 第三方许可证

本文件披露 GuardedCoder 直接运行与开发依赖的名称、当前安装版本、许可证与项目主页。版本取自生成本文件时的项目 `.venv`（`importlib.metadata` / wheel METADATA），不是凭记忆填写。

完整锁定图见 `requirements.txt` 与 `requirements-dev.txt`（pip-tools `--generate-hashes`）。

SecretStorage 是 `requirements.in` 中的直接依赖（Linux keyring 后端），本 Windows 生成环境未安装该包；下列版本与许可证来自 PyPI wheel `secretstorage-3.5.0-py3-none-any.whl` 的 METADATA（`License-Expression: BSD-3-Clause`）。

## pydantic

- Name: pydantic
- Version: 2.13.4
- License / 许可证: MIT
- Homepage: https://github.com/pydantic/pydantic

## httpx

- Name: httpx
- Version: 0.28.1
- License / 许可证: BSD-3-Clause
- Homepage: https://github.com/encode/httpx

## keyring

- Name: keyring
- Version: 25.7.0
- License / 许可证: MIT
- Homepage: https://github.com/jaraco/keyring

## defusedxml

- Name: defusedxml
- Version: 0.7.1
- License / 许可证: PSFL (Python Software Foundation License)
- Homepage: https://github.com/tiran/defusedxml

## SecretStorage

- Name: SecretStorage
- Version: 3.5.0
- License / 许可证: BSD-3-Clause
- Homepage: https://github.com/mitya57/secretstorage

## pytest

- Name: pytest
- Version: 9.1.1
- License / 许可证: MIT
- Homepage: https://docs.pytest.org/en/latest/

## pip-tools

- Name: pip-tools
- Version: 7.6.1
- License / 许可证: BSD
- Homepage: https://github.com/jazzband/pip-tools/

## build

- Name: build
- Version: 1.5.0
- License / 许可证: MIT
- Homepage: https://build.pypa.io

## setuptools

- Name: setuptools
- Version: 84.0.0
- License / 许可证: MIT
- Homepage: https://github.com/pypa/setuptools

锁文件中由 pip-tools `--allow-unsafe` 钉住、构建/安装会用到的工具：

## pip

- Name: pip
- Version: 24.3.1（`.venv` 当前安装；`requirements-dev.txt` 锁定为 26.2.1）
- License / 许可证: MIT
- Homepage: https://pip.pypa.io/

`build` 的直接依赖（锁文件）：

## pyproject_hooks

- Name: pyproject_hooks
- Version: 1.2.0
- License / 许可证: MIT（Classifier: OSI Approved :: MIT License；METADATA 无 License 字段）
- Homepage: https://github.com/pypa/pyproject-hooks

## packaging

- Name: packaging
- Version: 26.3
- License / 许可证: Apache-2.0 OR BSD-2-Clause
- Homepage: https://github.com/pypa/packaging
