import functools
import logging
import psutil
import os
import sys


def getLoggers(name,
               logger_level=logging.ERROR,
               time_logger_level=logging.INFO,
               error_logger_level=logging.ERROR,
               success_logger_level=logging.INFO):
    logger = logging.getLogger(f"[LOGGER] {name}")

    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(message)s",
        datefmt="%m/%d/%Y %H:%M:%S",
        level=logger_level,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(os.path.join(os.getcwd(), "log.txt"))
        ]
    )
    logger.setLevel(logger_level)
    time_logger = logging.getLogger(f"[TIME_LOGGER] {name}")
    time_logger.setLevel(time_logger_level)  # Set log level for this logger

    error_logger = logging.getLogger(f"[ERROR_LOGGER] {name}")
    error_handler = logging.FileHandler(os.path.join(os.getcwd(), "error.txt"))
    error_formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(message)s",
        datefmt="%m/%d/%Y %H:%M:%S"
    )
    error_handler.setFormatter(error_formatter)
    error_logger.addHandler(error_handler)
    # error_logger.addHandler(logging.StreamHandler(sys.stdout))
    error_logger.setLevel(error_logger_level)

    success_logger = logging.getLogger(f"[SUCCESS_LOGGER] {name}")
    success_handler = logging.FileHandler(os.path.join(os.getcwd(), "success.txt"))
    success_formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(message)s",
        datefmt="%m/%d/%Y %H:%M:%S"
    )
    success_handler.setFormatter(success_formatter)
    success_logger.addHandler(success_handler)
    # success_logger.addHandler(logging.StreamHandler(sys.stdout))
    success_logger.setLevel(success_logger_level)

    memory_logger = logging.getLogger(f"[MEMORY_LOGGER] {name}")
    memory_handler = logging.FileHandler(os.path.join(os.getcwd(), "memory.txt"))
    memory_handler.setLevel(logging.INFO)
    memory_formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%m/%d/%Y %H:%M:%S"
    )
    memory_handler.setFormatter(memory_formatter)
    memory_logger.removeHandler(memory_logger.handlers[:])
    memory_logger.addHandler(memory_handler)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(memory_formatter)
    memory_logger.addHandler(stream_handler)
    memory_logger.setLevel(logging.INFO)


    def log_memory_usage(func):
        """
        A decorator that logs memory usage before, during, and after a function call.
        """

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            process = psutil.Process(os.getpid())
            memory_before = process.memory_info().rss / (1024 * 1024)  # Convert to MB
            before_str = f"Before calling {func.__name__}, memory usage: {memory_before:.1f} MB"
            exceptioned = False
            try:
                result = func(*args, **kwargs)
            except:
                exceptioned = True
                raise
            finally:
                memory_after = process.memory_info().rss / (1024 * 1024)  # Convert to MB
                after_str = f"After calling {func.__name__}, memory usage: {memory_after:.1f} MB"
                if memory_after - memory_before > 0:
                    memory_logger.info(f"Memory used by {func.__name__}: {(memory_after - memory_before):.1f} MB, exceptioned = {exceptioned}, {before_str}, {after_str}")

            return result

        return wrapper

    return logger, time_logger, error_logger, success_logger, log_memory_usage