"""Job-lifetime DNS relay: inherited listeners -> fixed public resolver only.

No host resolver, filesystem configuration, destination supplied by a request,
logging of queries, or standalone service. The broker kills this process with
its job group. A bounded pool handles TCP DNS and single-datagram UDP queries.
"""
import concurrent.futures
import selectors
import socket
import struct
import sys
import threading

UPSTREAM = ('1.1.1.1', 53)
SLOTS = threading.BoundedSemaphore(8)


def exactly(connection, size):
    result = bytearray()
    while len(result) < size:
        chunk = connection.recv(size-len(result))
        if not chunk:
            raise OSError('Incomplete DNS message')
        result.extend(chunk)
    return bytes(result)


def tcp_query(client):
    try:
        with client:
            client.settimeout(5)
            # One bounded DNS request per connection, not a generic TCP tunnel.
            size = struct.unpack('!H', exactly(client, 2))[0]
            if size < 12:
                return
            request = exactly(client, size)
            with socket.create_connection(UPSTREAM, timeout=5) as upstream:
                upstream.sendall(struct.pack('!H', size) + request)
                header = exactly(upstream, 2)
                answer = exactly(upstream, struct.unpack('!H', header)[0])
            client.sendall(header + answer)
    except OSError:
        pass
    finally:
        SLOTS.release()


def udp_query(listener, request, peer):
    try:
        if len(request) < 12:
            return
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream:
            upstream.settimeout(5)
            upstream.connect(UPSTREAM)
            upstream.send(request)
            answer = upstream.recv(65535)
        if len(answer) >= 12 and answer[:2] == request[:2]:
            listener.sendto(answer, peer)
    except OSError:
        pass
    finally:
        SLOTS.release()


def main():
    if len(sys.argv) < 3 or len(sys.argv) % 2 != 1:
        return 125
    listeners = [socket.socket(fileno=int(fd)) for fd in sys.argv[1:]]
    with selectors.DefaultSelector() as poll, concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for listener in listeners:
            poll.register(listener, selectors.EVENT_READ)
        while True:
            for key, _ in poll.select():
                listener = key.fileobj
                if listener.type == socket.SOCK_STREAM:
                    client, _ = listener.accept()
                    if SLOTS.acquire(blocking=False):
                        pool.submit(tcp_query, client)
                    else:
                        client.close()
                else:
                    data, peer = listener.recvfrom(65535)
                    if SLOTS.acquire(blocking=False):
                        pool.submit(udp_query, listener, data, peer)


if __name__ == '__main__':
    sys.exit(main())
