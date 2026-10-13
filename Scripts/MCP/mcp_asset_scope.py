def asset_targets(value, normalize=True):
    """/** @param value\t操作参数 @param normalize\t规范化为包路径 @return 明确的目标集合 */"""
    targets = set()
    if isinstance(value, str) and value.startswith("/Game/"):
        targets.add(value.split(".", 1)[0].split(":", 1)[0].rstrip("/") if normalize else value)
    if isinstance(value, dict):
        for item in value.values():
            targets.update(asset_targets(item, normalize))
    if isinstance(value, (list, tuple, set)):
        for item in value:
            targets.update(asset_targets(item, normalize))
    return targets


def conflicting_packages(packages, scope):
    """
    /**
     * @param packages	待核对包路径
     * @param scope	明确包或目录范围
     * @return 与范围相交的包 保留原始大小写
     */
    """
    roots = {path.casefold() for path in asset_targets(scope)}
    return {
        package for package in asset_targets(packages)
        if any(package.casefold() == root or package.casefold().startswith(root + "/") or root.startswith(package.casefold() + "/") for root in roots)
    }
