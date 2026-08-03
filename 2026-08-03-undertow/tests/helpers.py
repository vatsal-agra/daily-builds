import socket


def free_addr():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    addr = s.getsockname()
    s.close()
    return addr


def free_triplet():
    return free_addr(), free_addr(), free_addr()
