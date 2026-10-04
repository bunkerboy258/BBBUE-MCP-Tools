import argparse
import json
import struct
import zlib


def inspect_fbx(path, reference):
    """
    /**
     * 核验交付文件中实际存在的骨骼层级与网格蒙皮关联
     * @param path		二进制 FBX 路径
     * @param reference		UE 参考骨骼清单数据
     * @return 文件结构与骨名校验结果
     */
    """
    with open(path, "rb") as source:
        data = source.read()
    if data[:23] != b"Kaydara FBX Binary  \x00\x1a\x00":
        raise RuntimeError("文件不是二进制 FBX")

    version = struct.unpack_from("<I", data, 23)[0]
    header_format = "<IIIB"
    if version >= 7500:
        header_format = "<QQQB"
    header_size = struct.calcsize(header_format)
    scalars = {"Y": "h", "C": "?", "I": "i", "F": "f", "D": "d", "L": "q"}
    arrays = {"f": "f", "d": "d", "i": "i", "l": "q", "b": "B", "c": "B"}

    def read_property(offset):
        kind = chr(data[offset])
        offset += 1
        if kind in scalars:
            fmt = "<" + scalars[kind]
            return struct.unpack_from(fmt, data, offset)[0], offset + struct.calcsize(fmt)
        if kind in ("S", "R"):
            size = struct.unpack_from("<I", data, offset)[0]
            offset += 4
            value = data[offset:offset + size]
            if kind == "S":
                value = value.decode("utf-8")
            return value, offset + size
        if kind in arrays:
            count, encoding, size = struct.unpack_from("<III", data, offset)
            offset += 12
            value = data[offset:offset + size]
            if encoding == 1:
                value = zlib.decompress(value)
            if encoding not in (0, 1):
                raise RuntimeError("未知 FBX 数组编码")
            fmt = "<" + str(count) + arrays[kind]
            if len(value) != struct.calcsize(fmt):
                raise RuntimeError("FBX 数组长度不一致")
            return struct.unpack(fmt, value), offset + size
        raise RuntimeError("未知 FBX 属性类型 " + kind)

    def read_node(offset):
        end, count, property_size, name_size = struct.unpack_from(header_format, data, offset)
        if end == 0:
            return None, offset + header_size
        if end > len(data) or end <= offset:
            raise RuntimeError("FBX 节点边界损坏")
        offset += header_size
        name = data[offset:offset + name_size].decode("utf-8")
        offset += name_size
        property_end = offset + property_size
        properties = []
        for _ in range(count):
            value, offset = read_property(offset)
            properties.append(value)
        if offset != property_end:
            raise RuntimeError("FBX 属性块边界不一致")
        children = []
        while offset < end:
            child, offset = read_node(offset)
            if child is None:
                break
            children.append(child)
        return {"name": name, "properties": properties, "children": children}, end

    nodes = {}
    offset = 27
    while offset < len(data):
        node, offset = read_node(offset)
        if node is None:
            break
        nodes[node["name"]] = node

    objects = nodes["Objects"]["children"]
    connections = [node["properties"] for node in nodes["Connections"]["children"] if node["name"] == "C"]
    parents = {item[1]: item[2] for item in connections if item[0] == "OO"}
    models = {item["properties"][0]: item for item in objects if item["name"] == "Model"}
    bone_models = {key: item for key, item in models.items() if item["properties"][2] in ("LimbNode", "Root")}
    names = {key: item["properties"][1].split("\x00", 1)[0].removeprefix("Model::") for key, item in bone_models.items()}
    bone_parents = {item[1]: item[2] for item in connections if item[0] == "OO" and item[1] in bone_models and item[2] in bone_models}
    geometries = [item for item in objects if item["name"] == "Geometry" and item["properties"][2] == "Mesh"]
    skins = {item["properties"][0] for item in objects if item["name"] == "Deformer" and item["properties"][2] == "Skin"}
    clusters = [item for item in objects if item["name"] == "Deformer" and item["properties"][2] == "Cluster"]
    expected = {item["name"].casefold(): item for item in reference["bones"]}
    exported = {name.casefold(): name for name in names.values()}
    if len(exported) != len(names) or len(expected) != len(reference["bones"]):
        raise RuntimeError("骨骼清单存在重名")
    if set(exported) != set(expected):
        raise RuntimeError("FBX 骨名不匹配 " + str(set(expected).symmetric_difference(exported)))
    for key, name in names.items():
        actual_parent = names.get(bone_parents.get(key), "None")
        item = expected[name.casefold()]
        if "fbxName" in item and name != item["fbxName"]:
            raise RuntimeError("FBX 精确骨名不匹配 " + name)
        expected_parent = item["parent"]
        if expected_parent in ("", "None"):
            expected_parent = "None"
        if actual_parent.casefold() != expected_parent.casefold():
            raise RuntimeError("FBX 父骨不匹配 {} actual={} expected={}".format(name, actual_parent, expected_parent))
    if not geometries or not skins or not clusters:
        raise RuntimeError("FBX 缺少网格或蒙皮")
    geometry_ids = {item["properties"][0] for item in geometries}
    if not all(parents.get(key) in geometry_ids for key in skins):
        raise RuntimeError("蒙皮未关联到网格")
    weighted_count = 0
    for cluster in clusters:
        if parents.get(cluster["properties"][0]) not in skins:
            raise RuntimeError("骨骼蒙皮簇未关联到蒙皮")
        fields = {item["name"]: item["properties"] for item in cluster["children"]}
        indices = fields.get("Indexes", [()])[0]
        weights = fields.get("Weights", [()])[0]
        if len(indices) != len(weights) or any(value < 0 for value in weights):
            raise RuntimeError("蒙皮权重数据无效")
        weighted_count += len(indices)
    if weighted_count == 0:
        raise RuntimeError("FBX 没有有效蒙皮权重")
    vertex_count = sum(len(field["properties"][0]) // 3 for item in geometries for field in item["children"] if field["name"] == "Vertices")
    return {"fbxVersion": version, "boneCount": len(names), "hierarchyMatches": True, "meshCount": len(geometries), "controlPointCount": vertex_count, "skinCount": len(skins), "clusterCount": len(clusters), "weightEntryCount": weighted_count, "exportedBoneNames": exported}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("fbx")
    parser.add_argument("skeleton")
    arguments = parser.parse_args()
    with open(arguments.skeleton, encoding="utf-8") as source:
        reference = json.load(source)
    result = inspect_fbx(arguments.fbx, reference)
    result.pop("exportedBoneNames")
    print(json.dumps(result, ensure_ascii=False, indent=4))
