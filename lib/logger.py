import logging

def get_logger() -> logging.Logger:
    logger = logging.getLogger('bluetooth_2_usb')

    if not logger.handlers:
        logger.setLevel(logging.INFO)

        file_handler = logging.FileHandler('/var/log/bluetooth_2_usb/bluetooth_2_usb.log')
        stdout_handler = logging.StreamHandler()

        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%y-%m-%d %H:%M:%S')
        file_handler.setFormatter(formatter)
        stdout_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(stdout_handler)

    return logger
