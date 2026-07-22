#!/usr/bin/env python3
"""Forward a private Docker bridge listener to a loopback-only source API."""

from __future__ import annotations

import argparse
import ast
import asyncio
import ipaddress
import json
import logging
from collections.abc import Sequence

LOGGER = logging.getLogger(__name__)
BUFFER_SIZE = 65_536
MAXIMUM_CONNECTIONS = 32
MAXIMUM_DOCKER_IPAM_CONFIG_BYTES = 32_768
RFC1918_NETWORKS: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)


def private_ipv4(value: str) -> str:
    """Accept a non-loopback RFC1918 IPv4 bridge address only."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("listen host must be an IPv4 address") from error
    if not isinstance(address, ipaddress.IPv4Address) or not any(
        address in network for network in RFC1918_NETWORKS
    ):
        raise argparse.ArgumentTypeError(
            "listen host must be a non-loopback RFC1918 IPv4 Docker bridge address"
        )
    return str(address)


def tcp_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def docker_bridge_gateway(ipam_config_json: str) -> str:
    """Select the first RFC1918 IPv4 gateway from Docker IPAM configuration."""
    if len(ipam_config_json.encode("utf-8")) > MAXIMUM_DOCKER_IPAM_CONFIG_BYTES:
        raise ValueError("Docker bridge IPAM configuration exceeds the safety limit")
    try:
        configurations = json.loads(ipam_config_json)
    except json.JSONDecodeError:
        try:
            # Some Docker-compatible CLIs render the inspected list with single-quoted
            # mapping keys. literal_eval accepts only Python literals, never code.
            configurations = ast.literal_eval(ipam_config_json)
        except (MemoryError, RecursionError, SyntaxError, ValueError) as error:
            raise ValueError("Docker bridge IPAM configuration is not a safe list") from error
    if not isinstance(configurations, list):
        raise ValueError("Docker bridge IPAM configuration must be a list")
    for configuration in configurations:
        if not isinstance(configuration, dict):
            continue
        gateway = configuration.get("Gateway")
        if not isinstance(gateway, str):
            continue
        try:
            return private_ipv4(gateway)
        except argparse.ArgumentTypeError:
            continue
    raise ValueError("Docker bridge has no RFC1918 IPv4 gateway")


async def _copy(
    source: asyncio.StreamReader,
    destination: asyncio.StreamWriter,
) -> None:
    while chunk := await source.read(BUFFER_SIZE):
        destination.write(chunk)
        await destination.drain()
    if destination.can_write_eof():
        destination.write_eof()
        await destination.drain()


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except (ConnectionError, OSError):
        pass


async def _forward(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    *,
    target_port: int,
    slots: asyncio.Semaphore,
) -> None:
    async with slots:
        try:
            target_reader, target_writer = await asyncio.open_connection("127.0.0.1", target_port)
        except OSError:
            # Deliberately do not log client headers, bearer tokens or payloads.
            LOGGER.warning("Source API bridge could not reach loopback target")
            await _close(client_writer)
            return
        try:
            await asyncio.gather(
                _copy(client_reader, target_writer),
                _copy(target_reader, client_writer),
            )
        except (ConnectionError, OSError):
            pass
        finally:
            await _close(target_writer)
            await _close(client_writer)


async def serve(*, listen_host: str, listen_port: int, target_port: int) -> None:
    slots = asyncio.Semaphore(MAXIMUM_CONNECTIONS)

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _forward(reader, writer, target_port=target_port, slots=slots)

    server = await asyncio.start_server(
        handler,
        host=listen_host,
        port=listen_port,
        limit=BUFFER_SIZE,
        reuse_address=True,
    )
    LOGGER.info(
        "Source API bridge listening on private Docker bridge address %s:%s",
        listen_host,
        listen_port,
    )
    async with server:
        await server.serve_forever()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-host", type=private_ipv4)
    parser.add_argument("--listen-port", type=tcp_port)
    parser.add_argument("--target-port", type=tcp_port)
    parser.add_argument("--print-docker-bridge-gateway", metavar="IPAM_CONFIG_JSON")
    arguments = parser.parse_args(argv)
    if arguments.print_docker_bridge_gateway is not None:
        if any(
            value is not None
            for value in (arguments.listen_host, arguments.listen_port, arguments.target_port)
        ):
            parser.error("--print-docker-bridge-gateway cannot be combined with listener options")
        return arguments
    if any(
        value is None
        for value in (arguments.listen_host, arguments.listen_port, arguments.target_port)
    ):
        parser.error(
            "--listen-host, --listen-port and --target-port are required to start a bridge"
        )
    return arguments


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    arguments = parse_args(argv)
    if arguments.print_docker_bridge_gateway is not None:
        try:
            print(docker_bridge_gateway(arguments.print_docker_bridge_gateway))
        except ValueError as error:
            raise SystemExit(f"error: {error}") from error
        return
    assert arguments.listen_host is not None
    assert arguments.listen_port is not None
    assert arguments.target_port is not None
    asyncio.run(
        serve(
            listen_host=arguments.listen_host,
            listen_port=arguments.listen_port,
            target_port=arguments.target_port,
        )
    )


if __name__ == "__main__":
    main()
