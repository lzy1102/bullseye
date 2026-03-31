# Bullseye

## Running Tests

### Unit Tests
```bash
pytest tests/ -v
```

### Integration Tests
```bash
pytest tests/test_integration.py -v
```

### Coverage Report
```bash
pytest --cov=bullseye --cov-report=html tests/
```

### Run Specific Test
```bash
pytest tests/test_data_handlers.py -v
pytest tests/test_exit_logic.py -v
pytest tests/test_rpc.py -v
pytest tests/test_api_server.py -v
pytest tests/test_cli_commands.py -v
pytest tests/test_configuration.py -v
```

## Test Coverage Goals

- [ ] Data Handlers: 100% coverage
- [ ] Exit Logic: 100% coverage
- [ ] RPC Modules: 100% coverage
- [ ] API Server: 100% coverage
- [ ] CLI Commands: 100% coverage
- [ ] Analysis Tools: 100% coverage
- [ ] Configuration: 100% coverage
- [ ] Integration: 100% coverage
