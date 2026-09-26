import logging
import json
import traceback
import time
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import inspect
from functools import wraps

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


class StructuredLogger:
    """Enhanced structured logger that handles database operations"""

    def __init__(self, log_dir: str = "/app/logs", log_level: str = "INFO"):
        # Предупреждения и ошибки дублируются в stdlib-логгер → stdout → `docker logs`
        self.logger = logging.getLogger("bot")
        self.configure(log_dir, log_level)

    def configure(self, log_dir: str, log_level: str = "INFO"):
        """Перенастраивает этот же экземпляр: модули держат ссылку на него с момента импорта."""
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.min_level = _LEVELS.get(str(log_level).upper(), _LEVELS["INFO"])

        # Setup structured log file
        self.structured_log_file = self.log_dir / "bot_structured.log"
    
    def _get_caller_info(self, skip_frames: int = 2) -> Dict[str, Any]:
        """Get information about the calling function"""
        try:
            frame = inspect.currentframe()
            for _ in range(skip_frames):
                frame = frame.f_back
            
            filename = frame.f_code.co_filename
            function_name = frame.f_code.co_name
            line_number = frame.f_lineno
            
            # Extract module name from filename
            module_name = Path(filename).stem
            
            return {
                'module': module_name,
                'function': function_name,
                'line': line_number,
                'filename': filename
            }
        except Exception:
            return {
                'module': 'Unknown',
                'function': 'Unknown', 
                'line': 0,
                'filename': 'Unknown'
            }
    
    def log(
        self, 
        level: str,
        message: str,
        user_id: Optional[int] = None,
        session_id: Optional[int] = None,
        order_id: Optional[int] = None,
        comment: Optional[str] = None,
        product_name: Optional[str] = None,
        action: Optional[str] = None,
        execution_time: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
        exception: Optional[Exception] = None
    ):
        """Log a structured message"""
        numeric_level = _LEVELS.get(level, _LEVELS["INFO"])
        if numeric_level < self.min_level:
            return

        caller_info = self._get_caller_info(skip_frames=3)
        
        log_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': level,
            'message': message,
            'user_id': user_id,
            'session_id': session_id,
            'order_id': order_id,
            'comment': comment,
            'action': action,
            'product_name': product_name,
            'execution_time': execution_time,
            'module': caller_info['module'],
            'function': caller_info['function'],
            'line': caller_info['line'],
            'context': context
        }
        
        # Add stack trace for errors
        if exception or level in ['ERROR', 'CRITICAL']:
            if exception:
                log_entry['stack_trace'] = ''.join(traceback.format_exception(
                    type(exception), exception, exception.__traceback__
                ))
            else:
                log_entry['stack_trace'] = ''.join(traceback.format_stack())
        
        # Write to structured log file
        try:
            # default=str: Decimal/datetime в context раньше роняли json.dumps, и запись терялась
            line = json.dumps(log_entry, ensure_ascii=False, default=str)
            with open(self.structured_log_file, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception as e:
            # Fallback to stderr if log file write fails
            print(f"Failed to write to log file: {e}", file=sys.stderr)

        if numeric_level >= _LEVELS["WARNING"]:
            self.logger.log(
                numeric_level,
                "%s [action=%s user_id=%s order_id=%s %s:%s]",
                message, action, user_id, order_id, caller_info['module'], caller_info['line'],
                exc_info=(type(exception), exception, exception.__traceback__) if exception else None,
            )
    
    def debug(self, message: str, **kwargs):
        self.log('DEBUG', message, **kwargs)
    
    def info(self, message: str, **kwargs):
        self.log('INFO', message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self.log('WARNING', message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self.log('ERROR', message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        self.log('CRITICAL', message, **kwargs)

# Global logger instance
import os as _os
structured_logger = StructuredLogger(
    log_dir=_os.getenv("LOG_DIR", "/app/logs"),
    log_level=_os.getenv("LOG_LEVEL", "INFO"),
)

# Database operation logging decorators
def log_database_operation(
    operation_type: str = "database", 
    log_params: bool = True,
    log_success: bool = True,
    min_execution_time: float = 0.0
):
    """
    Decorator to log database operations
    
    Args:
        operation_type: Type of operation (db_select, db_insert, etc.)
        log_params: Whether to log function parameters
        log_success: Whether to log successful operations
        min_execution_time: Only log operations that take longer than this (in seconds)
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            user_id = kwargs.get('user_id') or getattr(args[0], 'user_id', None) if args else None
            
            # Extract relevant parameters for logging
            params_to_log = {}
            if log_params:
                # Log first few arguments (be careful with sensitive data)
                for i, arg in enumerate(args[:3]):  # Only first 3 args
                    if isinstance(arg, (str, int, float, bool)):
                        params_to_log[f'arg_{i}'] = arg
                
                # Log some kwargs (filter out sensitive ones)
                safe_kwargs = {k: v for k, v in kwargs.items() 
                             if k not in ['password', 'token', 'secret'] and 
                             isinstance(v, (str, int, float, bool, type(None)))}
                params_to_log.update(safe_kwargs)
            
            # Always log start for non-SELECT operations or slow operations
            should_log_start = operation_type != "db_select" or min_execution_time > 0
            
            if should_log_start:
                structured_logger.debug(
                    f"Starting {operation_type} operation: {func.__name__}",
                    user_id=user_id,
                    action=f"{operation_type}_{func.__name__}",
                    context=params_to_log
                )
            
            try:
                result = await func(*args, **kwargs)
                execution_time = time.time() - start_time
                
                # Only log if it meets criteria
                should_log_completion = (
                    log_success and 
                    (operation_type != "db_select" or execution_time >= min_execution_time)
                )
                
                if should_log_completion:
                    # WARNING только для медленных операций; при пороге 0 любая вставка была WARNING
                    is_slow = min_execution_time > 0 and execution_time >= min_execution_time
                    log_level = 'WARNING' if is_slow else 'INFO'
                    structured_logger.log(
                        log_level,
                        f"Completed {operation_type} operation: {func.__name__}",
                        user_id=user_id,
                        action=f"{operation_type}_{func.__name__}_success",
                        execution_time=round(execution_time, 3),
                        context={'result_type': type(result).__name__}
                    )
                
                return result
                
            except Exception as e:
                execution_time = time.time() - start_time
                structured_logger.error(
                    f"Failed {operation_type} operation: {func.__name__} - {str(e)}",
                    user_id=user_id,
                    action=f"{operation_type}_{func.__name__}_error", 
                    execution_time=round(execution_time, 3),
                    exception=e,
                    context=params_to_log
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            user_id = kwargs.get('user_id') or getattr(args[0], 'user_id', None) if args else None
            
            # Extract relevant parameters for logging
            params_to_log = {}
            if log_params:
                for i, arg in enumerate(args[:3]):
                    if isinstance(arg, (str, int, float, bool)):
                        params_to_log[f'arg_{i}'] = arg
                
                safe_kwargs = {k: v for k, v in kwargs.items() 
                             if k not in ['password', 'token', 'secret'] and 
                             isinstance(v, (str, int, float, bool, type(None)))}
                params_to_log.update(safe_kwargs)
            
            should_log_start = operation_type != "db_select" or min_execution_time > 0
            
            if should_log_start:
                structured_logger.debug(
                    f"Starting {operation_type} operation: {func.__name__}",
                    user_id=user_id,
                    action=f"{operation_type}_{func.__name__}",
                    context=params_to_log
                )
            
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                
                should_log_completion = (
                    log_success and 
                    (operation_type != "db_select" or execution_time >= min_execution_time)
                )
                
                if should_log_completion:
                    # WARNING только для медленных операций; при пороге 0 любая вставка была WARNING
                    is_slow = min_execution_time > 0 and execution_time >= min_execution_time
                    log_level = 'WARNING' if is_slow else 'INFO'
                    structured_logger.log(
                        log_level,
                        f"Completed {operation_type} operation: {func.__name__}",
                        user_id=user_id,
                        action=f"{operation_type}_{func.__name__}_success",
                        execution_time=round(execution_time, 3),
                        context={'result_type': type(result).__name__}
                    )
                
                return result
                
            except Exception as e:
                execution_time = time.time() - start_time
                structured_logger.error(
                    f"Failed {operation_type} operation: {func.__name__} - {str(e)}",
                    user_id=user_id,
                    action=f"{operation_type}_{func.__name__}_error",
                    execution_time=round(execution_time, 3),
                    exception=e,
                    context=params_to_log
                )
                raise
        
        # Return appropriate wrapper based on function type
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

# Specific decorators for different operations

def log_db_select(log_slow_only: bool = True, slow_threshold: float = 0.1):
    """
    Log database SELECT operations
    
    Args:
        log_slow_only: Only log SELECT operations that are slow
        slow_threshold: Threshold in seconds for what's considered slow
    """
    if log_slow_only:
        return log_database_operation(
            "db_select", 
            log_success=True, 
            min_execution_time=slow_threshold
        )
    else:
        return log_database_operation("db_select")

def log_db_insert(func):
    """Log database INSERT operations"""  
    return log_database_operation("db_insert")(func)

def log_db_update(func):
    """Log database UPDATE operations"""
    return log_database_operation("db_update")(func)

def log_db_delete(func):
    """Log database DELETE operations"""
    return log_database_operation("db_delete")(func)

def log_api_call(func):
    """Log API calls"""
    return log_database_operation("api_call")(func)

# FastAPI Middleware for automatic request logging
from fastapi import Request, Response
from typing import Callable
import uuid

# Option 1: Traditional Middleware Class (requires starlette in requirements.txt)
try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response as StarletteResponse
    
    class LoggingMiddleware(BaseHTTPMiddleware):
        """Middleware to automatically log all API requests"""
        
        async def dispatch(self, request: Request, call_next):
            # Generate unique request ID
            request_id = str(uuid.uuid4())[:8]
            start_time = time.time()
            
            # Extract user info if available (adjust based on your auth system)
            user_id = None
            if hasattr(request.state, 'user_id'):
                user_id = request.state.user_id
            elif 'user_id' in request.headers:
                try:
                    user_id = int(request.headers['user_id'])
                except (ValueError, TypeError):
                    pass
            
            # Log incoming request
            structured_logger.info(
                f"Incoming request: {request.method} {request.url.path}",
                user_id=user_id,
                action="http_request_start",
                context={
                    'request_id': request_id,
                    'method': request.method,
                    'path': str(request.url.path),
                    'query_params': dict(request.query_params),
                    'user_agent': request.headers.get('user-agent', 'Unknown'),
                    'ip_address': request.client.host if request.client else None
                }
            )
            
            try:
                # Process the request
                response: StarletteResponse = await call_next(request)
                execution_time = time.time() - start_time
                
                # Determine log level based on status code and execution time
                if response.status_code >= 500:
                    log_level = 'ERROR'
                elif response.status_code >= 400:
                    log_level = 'WARNING'
                elif execution_time > 2.0:  # Slow requests
                    log_level = 'WARNING'
                else:
                    log_level = 'INFO'
                
                # Log completed request
                structured_logger.log(
                    log_level,
                    f"Completed request: {request.method} {request.url.path} -> {response.status_code}",
                    user_id=user_id,
                    action="http_request_complete",
                    execution_time=round(execution_time, 3),
                    context={
                        'request_id': request_id,
                        'status_code': response.status_code,
                        'response_size': len(response.body) if hasattr(response, 'body') else None
                    }
                )
                
                return response
                
            except Exception as e:
                execution_time = time.time() - start_time
                
                # Log failed request
                structured_logger.error(
                    f"Failed request: {request.method} {request.url.path} - {str(e)}",
                    user_id=user_id,
                    action="http_request_error",
                    execution_time=round(execution_time, 3),
                    exception=e,
                    context={
                        'request_id': request_id
                    }
                )
                
                # Re-raise the exception
                raise

except ImportError:
    # Fallback if starlette imports fail
    LoggingMiddleware = None
    print("Warning: Starlette imports failed. LoggingMiddleware not available.")

# Option 2: FastAPI-native middleware function (always available)
def create_logging_middleware():
    """Create logging middleware function for FastAPI (no starlette dependency)"""
    
    async def log_requests(request: Request, call_next: Callable) -> Response:
        # Generate unique request ID
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        
        # Extract user info if available (adjust based to your auth system)
        user_id = None
        if hasattr(request.state, 'user_id'):
            user_id = request.state.user_id
        elif 'user_id' in request.headers:
            try:
                user_id = int(request.headers['user_id'])
            except (ValueError, TypeError):
                pass
        
        # Log incoming request
        structured_logger.info(
            f"Incoming request: {request.method} {request.url.path}",
            user_id=user_id,
            action="http_request_start",
            context={
                'request_id': request_id,
                'method': request.method,
                'path': str(request.url.path),
                'query_params': dict(request.query_params),
                'user_agent': request.headers.get('user-agent', 'Unknown'),
                'ip_address': request.client.host if request.client else None
            }
        )
        
        try:
            # Process the request
            response: Response = await call_next(request)
            execution_time = time.time() - start_time
            
            # Determine log level based on status code and execution time
            if response.status_code >= 500:
                log_level = 'ERROR'
            elif response.status_code >= 400:
                log_level = 'WARNING'
            elif execution_time > 2.0:  # Slow requests
                log_level = 'WARNING'
            else:
                log_level = 'INFO'
            
            # Log completed request
            structured_logger.log(
                log_level,
                f"Completed request: {request.method} {request.url.path} -> {response.status_code}",
                user_id=user_id,
                action="http_request_complete",
                execution_time=round(execution_time, 3),
                context={
                    'request_id': request_id,
                    'status_code': response.status_code,
                }
            )
            
            return response
            
        except Exception as e:
            execution_time = time.time() - start_time
            
            # Log failed request
            structured_logger.error(
                f"Failed request: {request.method} {request.url.path} - {str(e)}",
                user_id=user_id,
                action="http_request_error",
                execution_time=round(execution_time, 3),
                exception=e,
                context={
                    'request_id': request_id
                }
            )
            
            # Re-raise the exception
            raise
    
    return log_requests

# Performance monitoring decorator
def monitor_performance(threshold: float = 1.0):
    """
    Decorator to monitor function performance and log slow operations
    
    Args:
        threshold: Time in seconds above which to log a warning
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                execution_time = time.time() - start_time
                
                if execution_time > threshold:
                    user_id = kwargs.get('user_id') or getattr(args[0], 'user_id', None) if args else None
                    structured_logger.warning(
                        f"Slow operation detected: {func.__name__} took {execution_time:.3f}s",
                        user_id=user_id,
                        action="performance_warning",
                        execution_time=round(execution_time, 3),
                        context={'threshold': threshold}
                    )
                
                return result
            except Exception as e:
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                
                if execution_time > threshold:
                    user_id = kwargs.get('user_id') or getattr(args[0], 'user_id', None) if args else None
                    structured_logger.warning(
                        f"Slow operation detected: {func.__name__} took {execution_time:.3f}s",
                        user_id=user_id,
                        action="performance_warning",
                        execution_time=round(execution_time, 3),
                        context={'threshold': threshold}
                    )
                
                return result
            except Exception as e:
                raise
        
        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
    return decorator

# Context manager for manual logging blocks
class LoggingContext:
    """Context manager for logging blocks of code"""
    
    def __init__(self, operation_name: str, user_id: Optional[int] = None, **context):
        self.operation_name = operation_name
        self.user_id = user_id
        self.context = context
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        structured_logger.debug(
            f"Starting operation: {self.operation_name}",
            user_id=self.user_id,
            action=f"operation_{self.operation_name}_start",
            context=self.context
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        execution_time = time.time() - self.start_time
        
        if exc_type is None:
            structured_logger.info(
                f"Completed operation: {self.operation_name}",
                user_id=self.user_id,
                action=f"operation_{self.operation_name}_success",
                execution_time=round(execution_time, 3),
                context=self.context
            )
        else:
            structured_logger.error(
                f"Failed operation: {self.operation_name} - {str(exc_val)}",
                user_id=self.user_id,
                action=f"operation_{self.operation_name}_error",
                execution_time=round(execution_time, 3),
                exception=exc_val,
                context=self.context
            )

# Utility function for application startup
def setup_logging(
    log_dir: str = "/app/logs",
    log_level: str = "INFO",
    enable_console: bool = True
):
    """
    Setup application logging configuration
    
    Args:
        log_dir: Directory for log files
        log_level: Minimum log level
        enable_console: Whether to also log to console
    """
    # Перенастраиваем существующий экземпляр, а не создаём новый: остальные модули
    # импортировали structured_logger раньше и держат ссылку на старый объект.
    structured_logger.configure(log_dir, log_level)

    # stdlib logging (PTB, SQLAlchemy, наши предупреждения) → stdout, его читает `docker logs`
    level = getattr(logging, str(log_level).upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    if enable_console and not any(getattr(h, "_bot_console", False) for h in root.handlers):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler._bot_console = True
        console_handler.setFormatter(
            logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
        )
        root.addHandler(console_handler)

    # httpx на INFO пишет URL каждого запроса к Bot API — вместе с токеном бота
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # APScheduler на INFO пишет каждый запуск джобы
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    structured_logger.info(
        "Logging system initialized",
        action="logging_init",
        context={
            'log_dir': log_dir,
            'log_level': log_level,
            'console_enabled': enable_console
        }
    )