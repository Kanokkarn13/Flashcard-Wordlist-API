import logging
import json
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

class JSONFormatter(logging.Formatter):
    """Custom formatter to output logs in structured JSON format."""
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "filename": record.filename,
            "line_no": record.lineno,
        }
        # Add custom extra info if present
        if hasattr(record, "extra_info"):
            log_data.update(record.extra_info)
        return json.dumps(log_data, ensure_ascii=False)

def setup_logger():
    """Sets up standard logger configured with JSON stream handler."""
    logger = logging.getLogger("api")
    logger.setLevel(logging.INFO)
    
    # Avoid adding handlers multiple times in dev reload
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = JSONFormatter()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

logger = setup_logger()

class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log request details and execution duration in a structured format."""
    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()
        
        # Log request incoming
        logger.info(
            f"Incoming request: {request.method} {request.url.path}",
            extra={"extra_info": {
                "method": request.method,
                "path": request.url.path,
                "query_params": dict(request.query_params),
                "client_ip": request.client.host if request.client else "unknown"
            }}
        )
        
        try:
            response = await call_next(request)
            process_time = (time.perf_counter() - start_time) * 1000
            
            # Log completion
            logger.info(
                f"Completed request: {request.method} {request.url.path} with status {response.status_code}",
                extra={"extra_info": {
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "process_time_ms": round(process_time, 2)
                }}
            )
            return response
        except Exception as e:
            process_time = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"Failed request: {request.method} {request.url.path} - Error: {str(e)}",
                exc_info=True,
                extra={"extra_info": {
                    "method": request.method,
                    "path": request.url.path,
                    "process_time_ms": round(process_time, 2),
                    "error": str(e)
                }}
            )
            raise
