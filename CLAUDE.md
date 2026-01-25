# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A file backup tool that scans local files/directories and uploads them to Baidu Pan with encryption. This is a refactored version of `object_backup_to_baidu_pan`.

## Commands

```bash
# Run the main application
python -m simple_object_backup_to_pan_baidu

# Run specific modules directly
python -m simple_object_backup_to_pan_baidu.config
python -m simple_object_backup_to_pan_baidu.db_service
python -m simple_object_backup_to_pan_baidu.logger
```

## Architecture

### Configuration System (`config.py`)
- Uses `Config` Pydantic model with default values
- Loads custom settings from `config.toml` via `tomllib`
- Overrides with environment variables from `mysql.env` and `baidupan.env`
- Uses singleton pattern via `get_config()` function
- Custom string parsing: `'true'`/`'false'`→bool, `'none'`→None, expressions like `'20*1024*1024'`→int

### Database Layer (`db_service.py`, `scan_service.py`)
- **DbService**: Creates SQLAlchemy engine with connection pooling
- **ScanService**: Scans files/directories and persists `ScanResult` to `scan_results` table
- **DbMixin**: Base class adding `id`, `created_at`, `updated_at` to all tables
- **Retry decorator**: `@retry_decorator()` with exponential backoff for DB operations

### Service Pattern (`domain.py`)
- **BaseService**: Abstract base class for services using thread/process pools
- Uses `ThreadPoolExecutor` or `ProcessPoolExecutor`
- Methods: `submit_task()`, `stop_accepting_tasks()`, `wait_for_completion()`, `shutdown_executor()`

### Logging (`logger.py`)
- **LoggerService**: Singleton pattern with queued background worker
- Starts automatically on first `get_logger()` call
- Configurable handlers: console, size-rotating files, time-rotating files, error-only file
- Three formatter presets: `debug`, `service`, `main`

### Graceful Shutdown (`shutdown_manager.py`)
- **GracefulShutdownManager**: Handles SIGINT/SIGTERM signals
- Shutdown sequence: stop accepting → notify services → wait for tasks → close pools → cleanup
- Supports `force_shutdown()` for emergency termination

### Database Tables
- `scan_results`: Stores scanned file/directory metadata (host_name, object_path, size, items)
- `status_finished`: Tracks completion status for operations

## Configuration Files

- `config.toml`: Main configuration (DB pool, paths, compression, upload settings)
- `mysql.env`: DB credentials (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_DATABASE`)
- `baidupan.env`: Baidu Pan upload credentials

## Key Patterns

1. **Singleton services**: Config, LoggerService use singleton pattern
2. **Executor-based services**: Services extend BaseService for task submission
3. **DB retry wrapper**: All DB operations use `@retry_decorator()` for resilience
4. **Pydantic models**: Config and ScanResult use Pydantic for validation
5. **SQLAlchemy ORM**: Uses DeclarativeBase with mapped columns

使用uv add 添加依赖。
使用uv run -m 运行代码

