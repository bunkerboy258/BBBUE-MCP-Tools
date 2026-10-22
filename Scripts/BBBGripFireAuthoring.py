import copy
import hashlib

import unreal

from BBBAssetWritePolicy import require_asset_write


def hold_signature(recipe, project):
    """/** @param recipe 未开火制作源 @param project 项目根 @return 正式未开火姿势与标定摘要 */"""
    from BBBGripAuthoringToolset import _definition, _digest

    animation = project / 'Content' / (recipe['animation'].removeprefix('/Game/') + '.uasset')
    _, calibration = _definition(recipe)
    return _digest({'animation': recipe['animation'], 'bytes': hashlib.sha256(animation.read_bytes()).hexdigest(),
                    'calibration': calibration})


def prepare(hold, hold_path, project):
    """/** @param hold 未开火制作源 @param hold_path 未开火制作路径 @param project 项目根 @return 从已应用未开火结果打开开火手指制作 不应用运行配置 */"""
    from BBBGripAuthoringToolset import _fingerprint, _recipe, _write_recipe

    if hold.get('grip_role') == 'fire':
        raise RuntimeError('FIRE_GRIP_REQUIRES_HOLD_RECIPE: 请提供未开火制作源')
    if not hold.get('manual_edit', {}).get('definitionApplied') or hold.get('validation', {}).get('fingerprint') != _fingerprint(hold, project):
        raise RuntimeError('FIRE_GRIP_REQUIRES_HOLD_APPLY: 先应用本枪当前未开火握姿')
    fire_path = hold_path.with_name(hold_path.name.replace('_HandGrip_', '_FireGrip_'))
    if fire_path == hold_path:
        raise RuntimeError('FIRE_GRIP_RECIPE_NAME_REQUIRED')
    signature = hold_signature(hold, project)
    if fire_path.exists():
        recipe = _recipe(fire_path, hold['weapon_root'])
        if recipe.get('hold_signature') != signature:
            raise RuntimeError('FIRE_GRIP_BASE_CHANGED: 未开火基准已变更 请明确要求重新建立开火底稿 现有手工内容保留')
        return _open(recipe, fire_path, project, hold['animation'])
    recipe = copy.deepcopy(hold)
    recipe['grip_role'] = 'fire'
    recipe['hold_recipe'] = str(hold_path.relative_to(project)).replace('\\', '/')
    recipe['hold_signature'] = signature
    for field in ('rig', 'sequence', 'animation'):
        recipe[field] = hold[field].replace('_HandGrip', '_FireGrip')
        if recipe[field] == hold[field] or unreal.EditorAssetLibrary.does_asset_exist(recipe[field]):
            raise RuntimeError('FIRE_GRIP_DESTINATION_EXISTS: ' + recipe[field])
    for field in ('manual_edit', 'validation', 'review'):
        recipe.pop(field, None)
    require_asset_write([], [recipe[field] for field in ('rig', 'sequence', 'animation')])
    for field in ('rig', 'sequence', 'animation'):
        folder, name = recipe[field].rsplit('/', 1)
        source = unreal.load_asset(hold[field])
        created = unreal.AssetToolsHelpers.get_asset_tools().duplicate_asset(name, folder, source)
        if created is None or not unreal.EditorAssetLibrary.save_loaded_asset(created, False):
            raise RuntimeError('FIRE_GRIP_CREATE_FAILED: ' + recipe[field])
    _write_recipe(fire_path, recipe, project)
    return _open(recipe, fire_path, project, hold['animation'])


def _open(recipe, fire_path, project, seed):
    """/** @param recipe 开火制作源 @param fire_path 制作路径 @param project 项目根 @param seed 未开火输入 @return 仅显示手指的实际制作序列 */"""
    import BBBGripManualAuthoring as manual
    from BBBGripAuthoringToolset import _asset

    result = manual.prepare(recipe, fire_path, project)
    asset = _asset(recipe['rig'], unreal.ControlRigBlueprint)
    sequence = _asset(recipe['sequence'], unreal.LevelSequence)
    hierarchies = [asset.hierarchy, manual._instance(sequence).get_hierarchy()]
    for hierarchy in hierarchies:
        for name in ('fk_hand_r', 'hand_l_ik_ctrl', 'elbow_l_pv_ctrl'):
            key = manual._key(name, 'CONTROL')
            settings = hierarchy.get_control_settings(key)
            settings.shape_visible = False
            hierarchy.set_control_settings(key, settings, False, True, False)
    unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
    unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
    result.update({'gripRole': 'fire', 'recipe': str(fire_path.relative_to(project)).replace('\\', '/'),
                   'seed': seed, 'calibrationShared': True, 'next': 'manual_apply_fire'})
    return result


def apply(hold, hold_path, project):
    """/** @param hold 未开火制作源 @param hold_path 未开火制作路径 @param project 项目根 @return 应用当前开火底稿 只写手指握姿引用 */"""
    import BBBGripManualAuthoring as manual
    from BBBGripAuthoringToolset import _recipe

    fire_path = hold_path.with_name(hold_path.name.replace('_HandGrip_', '_FireGrip_'))
    if not fire_path.is_file():
        raise RuntimeError('FIRE_GRIP_PREPARE_REQUIRED')
    recipe = _recipe(fire_path, hold['weapon_root'])
    if recipe.get('hold_signature') != hold_signature(hold, project):
        raise RuntimeError('FIRE_GRIP_BASE_CHANGED: 禁止应用基于旧未开火握姿的开火底稿')
    return manual.apply(recipe, fire_path, project)
