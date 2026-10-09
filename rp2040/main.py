"""Boot entry point for a demo board with the official Tiny Tapeout SDK installed."""


def main():
    # Keep SDK diagnostics out of JSON responses. Startup lines are tolerated.
    try:
        import ttboard.log as logging
        logging.basicConfig(level=logging.ERROR)
    except ImportError:
        pass

    try:
        from ttboard.boot.demoboard_detect import DemoboardDetect
    except ImportError:
        DemoboardDetect = None  # Older SDKs detect from DemoBoard.get().
    if DemoboardDetect is not None and not DemoboardDetect.probe():
        raise RuntimeError("El SDK no detecto la placa/carrier/shuttle.")

    from ttboard.demoboard import DemoBoard
    from ttboard.mode import RPMode
    from omega_board_server import BoardController, serve

    tt = DemoBoard.get()
    controller = BoardController(tt, RPMode.ASIC_RP_CONTROL)
    print("OMEGA_JSON_SERVER_READY v1")
    try:
        serve(controller)
    finally:
        controller.shutdown()


if __name__ == "__main__":
    main()
