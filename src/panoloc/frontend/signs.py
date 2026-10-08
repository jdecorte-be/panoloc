SIGN_NAMES = {
    # danger
    "A13b": "Pedestrian crossing ahead",
    # intersection and priority
    "AB3": "Give way",
    "AB3a": "Give way",
    "AB4": "Stop",
    "AB6": "Priority road",
    # prohibition
    "B0": "Closed to all vehicles",
    "B1": "No entry",
    "B2a": "No left turn",
    "B3": "No overtaking",
    "B6a1": "No parking",
    "B6d": "No stopping or parking",
    "B14": "Speed limit",
    # obligation
    "B21a1": "Keep right",
    "B21a2": "Keep left",
    "B22a": "Mandatory cycle lane",
    "B27a": "Bus lane",
    # services
    "CE14": "Accessible to disabled people",
    # sub-panels (panonceaux)
    "M6h": "Disabled parking only",
    "M6i": "EV charging only",
    "M9v": "Except cyclists",
    "M9v1": "Except cyclists",
    "M12d": "Cyclists may turn right on red",
    "M12f": "Cyclists may go straight on red",
    "M12g": "Cyclists may turn left on red",
    "M12fd": "Cyclists may go straight or right on red",
    "M12gf": "Cyclists may go left or straight on red",
    "M12gd": "Cyclists may turn left or right on red",
    "M12gfd": "Cyclists may go any way on red",
}


def sign_name(traffic_sign):
    codes = [c.removeprefix("FR:") for c in traffic_sign.split(";")]
    names = [SIGN_NAMES.get(c.partition("[")[0]) for c in codes]
    if not any(names):
        return traffic_sign
    return f"{' + '.join(n or c for n, c in zip(names, codes))} ({';'.join(codes)})"
