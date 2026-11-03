"""离线校准 FBX 面朝向 保留每个角点的法线与 UV 以及全部蒙皮数据。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True


def _fields(node):
    """/** @param node FBX 节点 @return 直属字段映射 */"""
    return {child.id: child for child in node.elems}


def _orientation(geometry):
    """/** @param geometry 三角面网格节点 @return 按面积加权的朝向与多边形角点范围 */"""
    fields = _fields(geometry)
    vertices = fields[b'Vertices'].props[0]
    polygons = fields[b'PolygonVertexIndex'].props[0]
    normals = _fields(fields[b'LayerElementNormal'])
    if normals[b'MappingInformationType'].props[0] != b'ByPolygonVertex':
        raise RuntimeError('需要逐角点法线')
    values = normals[b'Normals'].props[0]
    indices = normals[b'NormalsIndex'].props[0] if b'NormalsIndex' in normals else range(len(polygons))
    positive = 0.0
    negative = 0.0
    faces = []
    begin = 0
    for end, value in enumerate(polygons):
        if value >= 0:
            continue
        face = [int(index) if index >= 0 else -int(index)-1 for index in polygons[begin:end+1]]
        if len(face) != 3:
            raise RuntimeError('需要明确三角化的正式制作源')
        a, b, c = [vertices[index*3:index*3+3] for index in face]
        x = [b[index]-a[index] for index in range(3)]
        y = [c[index]-a[index] for index in range(3)]
        cross = [x[1]*y[2]-x[2]*y[1], x[2]*y[0]-x[0]*y[2], x[0]*y[1]-x[1]*y[0]]
        normal = [sum(values[indices[corner]*3+axis] for corner in range(begin, end+1)) for axis in range(3)]
        dot = sum(cross[index]*normal[index] for index in range(3))
        positive += max(0, dot)
        negative += max(0, -dot)
        faces.append((begin, end+1))
        begin = end+1
    if begin != len(polygons) or positive+negative <= 0:
        raise RuntimeError('面索引未结束或法线全部退化')
    return positive/(positive+negative), faces


def _remap_corners(geometry, faces):
    """/** @param geometry 原网格 @param faces 逐面角点范围 @return 只交换面顺序与相应角点索引的节点清单 */"""
    permutation = [index for begin, end in faces for index in (begin, end-1, begin+1)]
    fields = _fields(geometry)
    polygons = fields[b'PolygonVertexIndex']
    original = [int(value) if value >= 0 else -int(value)-1 for value in polygons.props[0]]
    result = [original[index] for index in permutation]
    for _, end in faces:
        result[end-1] = -result[end-1]-1
    updates = [(polygons, type(polygons.props[0])(polygons.props[0].typecode, result))]
    for layer in geometry.elems:
        if not layer.id.startswith(b'LayerElement'):
            continue
        attributes = _fields(layer)
        if attributes[b'MappingInformationType'].props[0] != b'ByPolygonVertex':
            continue
        reference = attributes[b'ReferenceInformationType'].props[0]
        if reference == b'IndexToDirect':
            indices = [node for node in layer.elems if node.id.endswith((b'Index', b'Indexes'))]
            if len(indices) != 1 or len(indices[0].props[0]) != len(permutation):
                raise RuntimeError('角点索引数量不符 '+str(layer.id))
            node = indices[0]
            data = node.props[0]
            updates.append((node, type(data)(data.typecode, [data[index] for index in permutation])))
            continue
        if reference != b'Direct':
            raise RuntimeError('不支持的角点引用 '+str(layer.id))
        values = [node for node in layer.elems if node.props and hasattr(node.props[0], 'typecode')]
        if len(values) != 1:
            raise RuntimeError('直接角点数据不唯一 '+str(layer.id))
        node = values[0]
        data = node.props[0]
        width, remainder = divmod(len(data), len(permutation))
        if remainder or width not in (1, 2, 3, 4):
            raise RuntimeError('角点属性维度不符')
        updates.append((node, type(data)(data.typecode, [data[index*width+axis] for index in permutation for axis in range(width)])))
    changed = {id(node) for node, _ in updates}
    preserved = _digest(geometry, changed)
    for node, value in updates:
        node.props[0] = value
    if _digest(geometry, changed) != preserved:
        raise RuntimeError('朝向校准改变了非角点索引数据')
    return changed


def _digest(node, excluded):
    """/** @param node FBX 子树 @param excluded 明确允许变更的节点 @return 其它原始属性的完整性摘要 */"""
    value = hashlib.sha256()
    def visit(item):
        """/** @param item 当前节点 @return 将原始属性递归纳入摘要 */"""
        value.update(item.id)
        if id(item) not in excluded:
            for prop in item.props:
                value.update(prop.tobytes() if hasattr(prop, 'tobytes') else repr(prop).encode())
        for child in item.elems:
            visit(child)
    visit(node)
    return value.hexdigest()


def normalize_winding(filename, apply=False):
    """/** @param filename 已三角化的明确 FBX @param apply 是否原位校准 @return 正反面面积比例与保存后的完整性回读 */"""
    from io_scene_fbx import parse_fbx, encode_bin

    path = Path(filename).absolute()
    if path.resolve() != path or path.suffix.lower() != '.fbx' or not path.is_file():
        raise RuntimeError('需要无链接的明确 FBX 文件')
    tree, version = parse_fbx.parse(str(path))
    objects = _fields(tree)[b'Objects']
    meshes = [node for node in objects.elems if node.id == b'Geometry' and node.props[2] == b'Mesh']
    if not meshes:
        raise RuntimeError('FBX 没有网格')
    orientations = [_orientation(mesh) for mesh in meshes]
    if any(.1 < ratio < .9 for ratio, _ in orientations):
        raise RuntimeError('网格正反面混杂 不能整体校准')
    report = {'file': str(path), 'meshes': [{'triangles':len(faces), 'outwardAreaRatio':ratio} for ratio, faces in orientations], 'changed':False}
    if not apply or all(ratio >= .9 for ratio, _ in orientations):
        return report
    changed = set()
    original = _digest(tree, set())
    for mesh, (ratio, faces) in zip(meshes, orientations):
        if ratio < .1:
            changed.update(_remap_corners(mesh, faces))
    preserved = _digest(tree, changed)
    def convert(node):
        """/** @param node 解析节点 @return 保持原始属性类型的写入节点 */"""
        methods = {'B':'add_bool', 'C':'add_char', 'Z':'add_int8', 'Y':'add_int16', 'I':'add_int32', 'L':'add_int64', 'F':'add_float32', 'D':'add_float64', 'R':'add_bytes', 'S':'add_string', 'i':'add_int32_array', 'l':'add_int64_array', 'f':'add_float32_array', 'd':'add_float64_array', 'b':'add_bool_array', 'c':'add_byte_array'}
        result = encode_bin.FBXElem(node.id)
        for kind, value in zip(node.props_type, node.props):
            getattr(result, methods[chr(kind)])(value)
        result.elems = [convert(child) for child in node.elems]
        return result
    temporary = path.with_suffix('.winding.fbx')
    if temporary.exists() or temporary.parent.resolve() != path.parent.resolve():
        raise RuntimeError('制作暂存路径无效或已存在')
    encode_bin.write(str(temporary), convert(tree), version)
    actual, actual_version = parse_fbx.parse(str(temporary))
    if actual_version != version or _digest(actual, set()) != _digest(tree, set()):
        raise RuntimeError('FBX 写入回读不符')
    if _digest(tree, changed) != preserved or _digest(tree, set()) == original:
        raise RuntimeError('FBX 校准完整性检查失败')
    if any(_orientation(mesh)[0] < .9 for mesh in meshes):
        raise RuntimeError('校准后仍有大面积反面')
    os.replace(temporary, path)
    report['changed'] = True
    report['outwardAreaRatioAfter'] = [_orientation(mesh)[0] for mesh in meshes]
    return report


if __name__ == '__main__':
    if os.name == 'nt':
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
    parser = argparse.ArgumentParser()
    parser.add_argument('--files', nargs='+', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:])
    print(json.dumps([normalize_winding(filename, args.apply) for filename in args.files]), flush=True)
