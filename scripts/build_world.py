"""Blender-side deterministic reconstruction of a WorldClaw-style scene."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils import noise as math_noise


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--asset", type=Path)
    p.add_argument("--asset-dir", type=Path)
    p.add_argument("--camera", choices=("all", "details", "global", "walk_village", "walk_river", "tower_close"), default="all")
    p.add_argument("--engine", choices=("eevee", "cycles"), default="eevee")
    p.add_argument("--samples", type=int)
    p.add_argument("--resolution-percent", type=int, default=100)
    p.add_argument("--skip-export", action="store_true")
    return p.parse_args(argv)


def material(name, color, metallic=0.0, roughness=0.7):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    nodes = mat.node_tree.nodes; links = mat.node_tree.links
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = .65 if name == "RiverWater" else 4.0
    noise.inputs["Detail"].default_value = 5.0
    noise.inputs["Roughness"].default_value = .72
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = .12 if name == "RiverWater" else .28
    bump.inputs["Distance"].default_value = .18
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    if name == "RiverWater":
        bsdf.inputs["IOR"].default_value = 1.333
        if "Transmission Weight" in bsdf.inputs:
            bsdf.inputs["Transmission Weight"].default_value = .62
        if "Coat Weight" in bsdf.inputs:
            bsdf.inputs["Coat Weight"].default_value = .18
        water_ramp = nodes.new("ShaderNodeValToRGB")
        water_ramp.color_ramp.elements[0].position = .23
        water_ramp.color_ramp.elements[0].color = (.005, .035, .045, 1.0)
        water_ramp.color_ramp.elements[1].position = .78
        water_ramp.color_ramp.elements[1].color = (.018, .16, .18, 1.0)
        links.new(noise.outputs["Fac"], water_ramp.inputs["Fac"])
        links.new(water_ramp.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position = .25
        ramp.color_ramp.elements[0].color = tuple(max(0.0, c*.55) for c in color) + (1,)
        ramp.color_ramp.elements[1].position = .78
        ramp.color_ramp.elements[1].color = tuple(min(1.0, c*1.45+.025) for c in color) + (1,)
        links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def smoothstep(edge0, edge1, value):
    t = max(0.0, min(1.0, (value - edge0) / max(edge1 - edge0, 1e-6)))
    return t * t * (3.0 - 2.0 * t)


def biome_weights(x, y, z):
    """Continuous semantic weights; unlike polygon labels these never create hard seams."""
    river_y = 7.0 * math.sin(x / 31.0) - 2.0
    river = 1.0 - smoothstep(5.2, 9.2, abs(y - river_y))
    village = 1.0 - smoothstep(15.0, 27.0, math.hypot(x - 29.0, y - 23.0))
    highland = max(smoothstep(8.5, 16.5, z), smoothstep(57.0, 83.0, abs(y)))
    forest_score = math.sin(x * 0.055 - y * 0.025) + math.cos(y * 0.075)
    forest = smoothstep(0.08, 1.05, forest_score)
    forest *= (1.0 - river) * (1.0 - village) * (1.0 - highland)
    return {"river_weight": river, "village_weight": village, "highland_weight": highland, "forest_weight": forest}


def terrain_pbr_material(project_root):
    """Build one tiled, continuously blended material from vetted CC0 PBR scans."""
    mat = bpy.data.materials.new("Continuous_CC0_Biome_PBR")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.82
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    coord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (62.0, 62.0, 62.0)
    links.new(coord.outputs["Generated"], mapping.inputs["Vector"])

    roots = {
        "meadow": project_root / "assets/external/polyhaven/materials/aerial_grass_rock",
        "forest": project_root / "assets/external/polyhaven/materials/forrest_ground_01",
        "highland": project_root / "assets/external/polyhaven/materials/forest_ground_04",
        "village": project_root / "assets/external/polyhaven/materials/forest_ground_04",
        "river": project_root / "assets/external/polyhaven/materials/forrest_ground_01",
    }

    def map_node(label, token, fallback, non_color=False):
        node = nodes.new("ShaderNodeTexImage")
        matches = sorted(roots[label].glob(f"*_{token}_2k.jpg"))
        if matches:
            node.image = bpy.data.images.load(str(matches[0]), check_existing=True)
            if non_color:
                node.image.colorspace_settings.name = "Non-Color"
            node.extension = "REPEAT"
            node.interpolation = "Smart"
            links.new(mapping.outputs["Vector"], node.inputs["Vector"])
            return node.outputs["Color"]
        value = nodes.new("ShaderNodeRGB")
        value.outputs[0].default_value = fallback
        return value.outputs[0]

    colors = {
        key: map_node(key, "diff", (0.18, 0.28, 0.10, 1.0))
        for key in roots
    }
    color_tints = {
        "meadow": (0.68, 0.98, 0.46, 1.0),
        "forest": (0.46, 0.68, 0.38, 1.0),
        "highland": (0.30, 0.34, 0.35, 1.0),
        "village": (0.86, 0.72, 0.54, 1.0),
        "river": (0.38, 0.48, 0.36, 1.0),
    }
    for key, source in tuple(colors.items()):
        tint_node = nodes.new("ShaderNodeMixRGB")
        tint_node.blend_type = "MULTIPLY"
        tint_node.inputs["Fac"].default_value = 0.84 if key == "highland" else 0.58
        tint_node.inputs["Color2"].default_value = color_tints[key]
        links.new(source, tint_node.inputs["Color1"])
        colors[key] = tint_node.outputs["Color"]
    roughness = {
        key: map_node(key, "rough", (0.78, 0.78, 0.78, 1.0), True)
        for key in roots
    }
    normal = {
        key: map_node(key, "nor_gl", (0.5, 0.5, 1.0, 1.0), True)
        for key in roots
    }
    displacement = {
        key: map_node(key, "disp", (0.5, 0.5, 0.5, 1.0), True)
        for key in roots
    }

    attrs = {}
    for name in ("forest_weight", "highland_weight", "village_weight", "river_weight"):
        attr = nodes.new("ShaderNodeAttribute")
        attr.attribute_name = name
        attrs[name] = attr.outputs["Fac"]

    def blend_chain(sources):
        current = sources["meadow"]
        for label, attr_name in (
            ("forest", "forest_weight"),
            ("highland", "highland_weight"),
            ("village", "village_weight"),
            ("river", "river_weight"),
        ):
            mix = nodes.new("ShaderNodeMixRGB")
            mix.blend_type = "MIX"
            links.new(attrs[attr_name], mix.inputs["Fac"])
            links.new(current, mix.inputs["Color1"])
            links.new(sources[label], mix.inputs["Color2"])
            current = mix.outputs["Color"]
        return current

    base_color = blend_chain(colors)
    # Gentle large-scale variation prevents the visibly tiled "wallpaper" look.
    macro = nodes.new("ShaderNodeTexNoise")
    macro.inputs["Scale"].default_value = 2.4
    macro.inputs["Detail"].default_value = 3.0
    macro.inputs["Roughness"].default_value = 0.7
    links.new(coord.outputs["Generated"], macro.inputs["Vector"])
    tint = nodes.new("ShaderNodeValToRGB")
    tint.color_ramp.elements[0].color = (0.68, 0.72, 0.62, 1.0)
    tint.color_ramp.elements[1].color = (1.08, 1.02, 0.88, 1.0)
    links.new(macro.outputs["Fac"], tint.inputs["Fac"])
    multiply = nodes.new("ShaderNodeMixRGB")
    multiply.blend_type = "MULTIPLY"; multiply.inputs["Fac"].default_value = 0.26
    links.new(base_color, multiply.inputs["Color1"])
    links.new(tint.outputs["Color"], multiply.inputs["Color2"])
    links.new(multiply.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(blend_chain(roughness), bsdf.inputs["Roughness"])

    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.inputs["Strength"].default_value = 0.58
    links.new(blend_chain(normal), normal_map.inputs["Color"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.28
    bump.inputs["Distance"].default_value = 0.12
    links.new(blend_chain(displacement), bump.inputs["Height"])
    links.new(normal_map.outputs["Normal"], bump.inputs["Normal"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def scanned_surface_material(name, root, uv_scale=12.0, tint=(0.78, 0.68, 0.52, 1.0)):
    """Compact PBR material for roads and other narrow authored surfaces."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    coord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (uv_scale, uv_scale, uv_scale)
    links.new(coord.outputs["Generated"], mapping.inputs["Vector"])

    def image_node(token, non_color=False):
        matches = sorted(root.glob(f"*_{token}_2k.jpg"))
        if not matches:
            return None
        node = nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(str(matches[0]), check_existing=True)
        if non_color:
            node.image.colorspace_settings.name = "Non-Color"
        node.extension = "REPEAT"
        node.interpolation = "Smart"
        links.new(mapping.outputs["Vector"], node.inputs["Vector"])
        return node

    diffuse = image_node("diff")
    if diffuse:
        grade = nodes.new("ShaderNodeMixRGB")
        grade.blend_type = "MULTIPLY"
        grade.inputs["Fac"].default_value = 0.34
        grade.inputs["Color2"].default_value = tint
        links.new(diffuse.outputs["Color"], grade.inputs["Color1"])
        links.new(grade.outputs["Color"], bsdf.inputs["Base Color"])
    rough = image_node("rough", True)
    if rough:
        links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])
    else:
        bsdf.inputs["Roughness"].default_value = 0.88
    normal = image_node("nor_gl", True)
    if normal:
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.inputs["Strength"].default_value = 0.72
        links.new(normal.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
    displacement = image_node("disp", True)
    if displacement:
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.24
        bump.inputs["Distance"].default_value = 0.09
        links.new(displacement.outputs["Color"], bump.inputs["Height"])
        if normal:
            links.new(normal_map.outputs["Normal"], bump.inputs["Normal"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def mountain_material():
    """Layered procedural rock that remains crisp on very large ridge meshes."""
    mat = bpy.data.materials.new("Distant_Mountain_Rock")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.91
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    coord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (4.8, 7.5, 4.2)
    links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 15.0
    noise.inputs["Detail"].default_value = 9.0
    noise.inputs["Roughness"].default_value = 0.78
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.25
    ramp.color_ramp.elements[0].color = (0.018, 0.022, 0.024, 1.0)
    ramp.color_ramp.elements[1].position = 0.78
    ramp.color_ramp.elements[1].color = (0.15, 0.14, 0.125, 1.0)
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.62
    bump.inputs["Distance"].default_value = 0.42
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def height_at(x, y):
    river_y = 7.0 * math.sin(x / 31.0) - 2.0
    river_d = abs(y - river_y)
    edge = max(0.0, (abs(y) - 25.0) / 55.0)
    hills = 14.0 * edge ** 1.45
    hills += 14.5 * math.exp(-((x + 36) ** 2 + (y - 38) ** 2) / 620.0)
    hills += 8.0 * math.exp(-((x - 47) ** 2 + (y - 40) ** 2) / 760.0)
    hills += 5.0 * math.exp(-((x - 58) ** 2 + (y + 42) ** 2) / 700.0)
    noise = 1.15 * math.sin(x * 0.105) * math.cos(y * 0.083)
    noise += 0.45 * math.sin(x * 0.31 + y * 0.22)
    z = 1.0 + hills + noise
    if river_d < 9.5:
        t = max(0.0, 1.0 - river_d / 9.5)
        z -= 4.8 * t * t
    village_d = math.hypot(x - 29.0, y - 23.0)
    if village_d < 21.0:
        blend = (1.0 - village_d / 21.0) ** 2
        z = z * (1.0 - 0.68 * blend) + 2.45 * (0.68 * blend)
    return z


def region_at(x, y, z=None):
    z = height_at(x, y) if z is None else z
    river_y = 7.0 * math.sin(x / 31.0) - 2.0
    if abs(y - river_y) < 6.4:
        return "river"
    if math.hypot(x - 29.0, y - 23.0) < 21.0:
        return "village"
    if z > 10.5 or abs(y) > 62:
        return "highlands"
    forest_score = math.sin(x * 0.055 - y * 0.025) + math.cos(y * 0.075)
    return "forest" if forest_score > 0.38 else "meadow"


def cube(name, loc, scale, mat, collection=None, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    o.data.materials.append(mat)
    if bevel:
        mod = o.modifiers.new("Soft edges", "BEVEL")
        mod.width, mod.segments = bevel, 2
    if collection:
        for c in list(o.users_collection): c.objects.unlink(o)
        collection.objects.link(o)
    return o


def cylinder(name, loc, radius, depth, mat, vertices=10, collection=None):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    o = bpy.context.object
    o.name = name
    o.data.materials.append(mat)
    if collection:
        for c in list(o.users_collection): c.objects.unlink(o)
        collection.objects.link(o)
    return o


def create_terrain(plan, terrain_mat, collection):
    res = plan["world"]["terrain_resolution"]
    extent = plan["world"]["extent_m"]
    verts, faces = [], []
    weights = {name: [] for name in ("river_weight", "village_weight", "highland_weight", "forest_weight")}
    for iy in range(res):
        y = -extent / 2 + extent * iy / (res - 1)
        for ix in range(res):
            x = -extent / 2 + extent * ix / (res - 1)
            z = height_at(x, y)
            verts.append((x, y, z))
            values = biome_weights(x, y, z)
            for name in weights:
                weights[name].append(values[name])
    for iy in range(res - 1):
        for ix in range(res - 1):
            a = iy * res + ix
            faces.append((a, a + 1, a + res + 1, a + res))
    mesh = bpy.data.meshes.new("ContinuousBiomeTerrainMesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    for name, values in weights.items():
        attribute = mesh.attributes.new(name=name, type="FLOAT", domain="POINT")
        attribute.data.foreach_set("value", values)
    mesh.materials.append(terrain_mat)
    for poly in mesh.polygons:
        poly.use_smooth = True
    obj = bpy.data.objects.new("Global_Continuous_PBR_Terrain", mesh)
    collection.objects.link(obj)
    return obj


def create_backdrop(mat, collection):
    """Give downward-looking overview cameras real ground beyond the edit area."""
    bpy.ops.mesh.primitive_plane_add(size=520, location=(0, 0, -4.2))
    obj = bpy.context.object
    obj.name = "Distant_Ground_Backdrop"
    obj.data.materials.append(mat)
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def create_mountain_range(name, y_center, depth, peaks, mat, collection, phase=0.0, base_z=-12.0):
    """Build a broad, overlapping alpine ridge rather than a flat horizon card."""
    nx, ny = 257, 65
    x_min, x_max = -320.0, 320.0
    verts, faces = [], []
    for iy in range(ny):
        v = iy / (ny - 1)
        y = y_center - depth * 0.5 + depth * v
        cross = math.sin(math.pi * v) ** 0.72
        for ix in range(nx):
            u = ix / (nx - 1)
            x = x_min + (x_max - x_min) * u
            peak_height = 0.0
            for px, height, spread in peaks:
                peak_height = max(peak_height, height * math.exp(-((x - px) / spread) ** 2))
            peak_height *= (
                0.94
                + 0.08 * math.sin(x * 0.16 + phase * 1.3)
                + 0.045 * math.sin(x * 0.39 - phase)
            )
            macro_noise = math_noise.fractal(
                Vector((x * 0.018, y * 0.027, phase * 1.91 + 0.37)),
                1.0, 2.05, 5.0,
            )
            fine_noise = math_noise.fractal(
                Vector((x * 0.061, y * 0.072, phase * 3.17 + 1.13)),
                1.0, 2.1, 4.0,
            )
            ridge_noise = 1.0 - abs(fine_noise)
            peak_height *= max(0.62, 0.94 + 0.18 * macro_noise + 0.10 * fine_noise)
            ridge_detail = (
                3.9 * math.sin(x * 0.087 + phase)
                + 2.2 * math.sin(x * 0.213 - phase * 0.7)
                + 1.1 * math.cos(x * 0.47 + v * 4.2)
            )
            erosion = (1.0 - abs(2.0 * v - 1.0)) * (
                4.2 * macro_noise + 2.0 * fine_noise + 2.6 * (ridge_noise - 0.5)
            )
            base = base_z + 2.4 * math.sin(x * 0.018 + phase)
            z = base + cross * max(0.0, peak_height + ridge_detail + erosion)
            verts.append((x, y, z))
    for iy in range(ny - 1):
        for ix in range(nx - 1):
            a = iy * nx + ix
            faces.append((a, a + 1, a + nx + 1, a + nx))
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    mesh.materials.append(mat)
    for poly in mesh.polygons:
        poly.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def create_mountain_ranges(mat, collection):
    create_mountain_range(
        "Near_Alpine_Ridge", 132.0, 74.0,
        ((-168, 60, 48), (-92, 70, 42), (-18, 64, 52), (62, 68, 45), (150, 61, 55)),
        mat, collection, 0.4, -14.0,
    )
    create_mountain_range(
        "Far_Alpine_Ridge", 188.0, 96.0,
        ((-190, 76, 58), (-112, 84, 48), (-32, 92, 52), (48, 80, 48), (122, 88, 52), (196, 74, 62)),
        mat, collection, 1.7, -22.0,
    )


def create_water(mat, collection):
    n, width = 96, 8.5
    verts, faces = [], []
    for i in range(n):
        x = -90 + 180 * i / (n - 1)
        cy = 7 * math.sin(x / 31) - 2
        verts.extend([(x, cy - width, 0.0), (x, cy + width, 0.0)])
    for i in range(n - 1): faces.append((2*i, 2*i+2, 2*i+3, 2*i+1))
    mesh = bpy.data.meshes.new("RiverRibbonMesh")
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(mat)
    obj = bpy.data.objects.new("Greenwater_River", mesh)
    collection.objects.link(obj)
    bevel = obj.modifiers.new("Water_Soften", "SUBSURF")
    bevel.levels = 2; bevel.render_levels = 2


def create_tree(name, x, y, mats, collection, scale=1.0):
    z = height_at(x, y)
    trunk = cylinder(name + "_trunk", (x, y, z + 1.35*scale), .28*scale, 2.7*scale, mats["wood"], 8, collection)
    bpy.ops.mesh.primitive_cone_add(vertices=9, radius1=1.75*scale, radius2=.12*scale, depth=4.6*scale, location=(x, y, z + 4.1*scale))
    crown = bpy.context.object
    crown.name = name + "_crown"
    crown.data.materials.append(mats["pine"])
    for c in list(crown.users_collection): c.objects.unlink(crown)
    collection.objects.link(crown)
    return trunk


def create_house(name, x, y, rot, mats, collection, scale=1.0):
    z = height_at(x, y)
    body = cube(name + "_walls", (x, y, z + 1.7*scale), (2.5*scale, 2.1*scale, 1.7*scale), mats["plaster"], collection, .12)
    body.rotation_euler[2] = rot
    bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=3.65*scale, radius2=0, depth=2.35*scale, location=(x, y, z + 4.45*scale), rotation=(0, 0, rot + math.pi/4))
    roof = bpy.context.object
    roof.name = name + "_roof"
    roof.scale.y = .82
    roof.data.materials.append(mats["roof"])
    for c in list(roof.users_collection): c.objects.unlink(roof)
    collection.objects.link(roof)
    door = cube(name + "_door", (x + math.cos(rot)*2.51*scale, y + math.sin(rot)*2.51*scale, z + 1.25*scale), (.12, .65*scale, 1.15*scale), mats["wood"], collection)
    door.rotation_euler[2] = rot


def create_bridge(mats, collection):
    x = 7.0
    cy = 7 * math.sin(x / 31) - 2
    z = 2.15
    deck = cube("Old_Timber_Bridge", (x, cy, z), (2.25, 7.2, .28), mats["wood"], collection, .08)
    for side in (-2.05, 2.05):
        for j in range(-3, 4):
            cylinder(f"BridgePost_{side}_{j}", (x+side, cy+j*2.0, z+1.0), .11, 1.8, mats["wood"], 8, collection)


def create_stone_circle(mats, collection):
    cx, cy = -48, -34
    for i in range(9):
        a = i * 2*math.pi/9
        x, y = cx + math.cos(a)*7, cy + math.sin(a)*7
        z = height_at(x, y)
        stone = cube(f"StandingStone_{i:02d}", (x, y, z+1.8), (.75, .55, 1.8+random.random()), mats["rock"], collection, .18)
        stone.rotation_euler = (random.uniform(-.12,.12), random.uniform(-.12,.12), a)


def create_procedural_tower(mats, collection):
    x, y = 42, 35
    z = height_at(x, y)
    cylinder("Procedural_Watchtower_Base", (x,y,z+4), 3.2, 8, mats["stone"], 10, collection)
    cube("Procedural_Watchtower_Deck", (x,y,z+8.1), (4.0,4.0,.45), mats["wood"], collection, .1)
    bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=5.0, depth=3.2, location=(x,y,z+11.0), rotation=(0,0,math.pi/4))
    roof=bpy.context.object; roof.name="Procedural_Watchtower_Roof"; roof.data.materials.append(mats["roof"])
    for c in list(roof.users_collection): c.objects.unlink(roof)
    collection.objects.link(roof)


def import_generated_asset(path, mats, collection):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    imported = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in imported if o.type == "MESH"]
    if not meshes: return False
    for o in imported:
        for c in list(o.users_collection): c.objects.unlink(o)
        collection.objects.link(o)
    minv = Vector((1e9,1e9,1e9)); maxv = Vector((-1e9,-1e9,-1e9))
    for o in meshes:
        for corner in o.bound_box:
            p=o.matrix_world @ Vector(corner)
            minv=Vector(map(min,minv,p)); maxv=Vector(map(max,maxv,p))
    size=maxv-minv; scale=11.5/max(size.z, .001)
    center=(minv+maxv)/2
    root=bpy.data.objects.new("Hunyuan3D_Watchtower_Instance",None); collection.objects.link(root)
    root.scale=(scale,scale,scale)
    root.location=(42-center.x*scale,35-center.y*scale,height_at(42,35)-minv.z*scale)
    for o in imported:
        if o.parent is None: o.parent=root
    # PBR-painted Hunyuan assets already carry albedo/metallic/roughness maps.
    # Only synthesize fallback materials for an untextured geometry-only GLB.
    for o in meshes:
        if o.data.materials:
            continue
        o.data.materials.append(mats["stone"])
        o.data.materials.append(mats["wood"])
        o.data.materials.append(mats["roof"])
        local_min=min(v.co.z for v in o.data.vertices)
        local_max=max(v.co.z for v in o.data.vertices)
        span=max(local_max-local_min,.001)
        for poly in o.data.polygons:
            avg_z=sum(o.data.vertices[i].co.z for i in poly.vertices)/len(poly.vertices)
            t=(avg_z-local_min)/span
            poly.material_index=2 if t>.79 else (1 if t>.56 else 0)
    return True


def load_asset_template(path, name):
    """Import a GLB once, then keep its meshes as a hidden linked template."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    imported = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in imported if o.type == "MESH"]
    if not meshes:
        return None
    source = bpy.data.collections.new("SOURCE_" + name)
    bpy.context.scene.collection.children.link(source)
    source.hide_render = True
    for o in imported:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        source.objects.link(o)
    minv = Vector((1e9, 1e9, 1e9)); maxv = Vector((-1e9, -1e9, -1e9))
    for o in meshes:
        for corner in o.bound_box:
            p = o.matrix_world @ Vector(corner)
            minv = Vector(map(min, minv, p)); maxv = Vector(map(max, maxv, p))
    return {"name": name, "objects": imported, "min": minv, "max": maxv}


def tint_template_materials(template, tint, strength, blend_type="MULTIPLY"):
    """Color-grade imported scans while keeping their original texture detail."""
    handled = set()
    for obj in template["objects"]:
        if obj.type != "MESH":
            continue
        for mat in obj.data.materials:
            if not mat or not mat.use_nodes or mat in handled:
                continue
            handled.add(mat)
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if not bsdf or not bsdf.inputs["Base Color"].is_linked:
                continue
            link = bsdf.inputs["Base Color"].links[0]
            source = link.from_socket
            mat.node_tree.links.remove(link)
            mix = mat.node_tree.nodes.new("ShaderNodeMixRGB")
            mix.blend_type = blend_type; mix.inputs["Fac"].default_value = strength
            mix.inputs["Color2"].default_value = (*tint, 1.0)
            mat.node_tree.links.new(source, mix.inputs["Color1"])
            mat.node_tree.links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])


def place_asset(template, name, x, y, rotation, target_size, collection, size_mode="height"):
    """Place a linked copy of a loaded asset without duplicating mesh memory."""
    size = template["max"] - template["min"]
    basis = size.z if size_mode == "height" else max(size.x, size.y, size.z)
    scale = target_size / max(basis, 0.001)
    center = (template["min"] + template["max"]) * 0.5
    root = bpy.data.objects.new(name, None); collection.objects.link(root)
    root.location = (x, y, height_at(x, y)); root.rotation_euler[2] = rotation
    root.scale = (scale, scale, scale)
    offset = bpy.data.objects.new(name + "_Origin", None); collection.objects.link(offset)
    offset.parent = root; offset.location = (-center.x, -center.y, -template["min"].z)
    mapping = {}
    for original in template["objects"]:
        clone = original.copy()
        if getattr(original, "data", None) is not None:
            clone.data = original.data
        collection.objects.link(clone)
        mapping[original] = clone
    for original, clone in mapping.items():
        if original.parent in mapping:
            clone.parent = mapping[original.parent]
            clone.matrix_parent_inverse = original.matrix_parent_inverse.copy()
            clone.matrix_local = original.matrix_local.copy()
        else:
            clone.parent = offset
            clone.matrix_parent_inverse = Matrix.Identity(4)
            clone.matrix_local = original.matrix_world.copy()
    return root


def make_curve(name, points, mat, collection, width=.35):
    curve=bpy.data.curves.new(name,"CURVE"); curve.dimensions="3D"; curve.bevel_depth=width; curve.bevel_resolution=2
    spline=curve.splines.new("BEZIER"); spline.bezier_points.add(len(points)-1)
    for bp,p in zip(spline.bezier_points,points): bp.co=p; bp.handle_left_type="AUTO"; bp.handle_right_type="AUTO"
    obj=bpy.data.objects.new(name,curve); curve.materials.append(mat); collection.objects.link(obj)


def make_path_ribbon(name, anchors, mat, collection, width=1.15, samples_per_segment=12):
    """Create a terrain-following road surface instead of a raised tube."""
    centers = []
    for index in range(len(anchors) - 1):
        a, b = Vector(anchors[index]), Vector(anchors[index + 1])
        for step in range(samples_per_segment):
            t = step / samples_per_segment
            p = a.lerp(b, t)
            centers.append(Vector((p.x, p.y, height_at(p.x, p.y) + 0.07)))
    p = Vector(anchors[-1])
    centers.append(Vector((p.x, p.y, height_at(p.x, p.y) + 0.07)))
    verts, faces = [], []
    for index, center in enumerate(centers):
        before = centers[max(0, index - 1)]
        after = centers[min(len(centers) - 1, index + 1)]
        tangent = after - before
        side = Vector((-tangent.y, tangent.x, 0.0)).normalized()
        local_width = width * (0.88 + 0.14 * math.sin(index * 0.73))
        verts.extend((center - side * local_width, center + side * local_width))
    for index in range(len(centers) - 1):
        faces.append((2 * index, 2 * index + 2, 2 * index + 3, 2 * index + 1))
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(verts, [], faces); mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh); collection.objects.link(obj)
    return obj


def create_fence_line(name, start, end, mat, collection, posts=7):
    start, end = Vector(start), Vector(end)
    delta = end - start
    angle = math.atan2(delta.y, delta.x)
    length = math.hypot(delta.x, delta.y)
    for index in range(posts):
        t = index / max(posts - 1, 1)
        x = start.x + delta.x * t; y = start.y + delta.y * t; z = height_at(x, y)
        post = cylinder(f"{name}_Post_{index:02d}", (x, y, z + 0.72), 0.10, 1.44, mat, 8, collection)
        post.rotation_euler[0] = random.uniform(-0.045, 0.045)
        post.rotation_euler[1] = random.uniform(-0.045, 0.045)
    midpoint = (start + end) * 0.5
    for rail_index, rail_height in enumerate((0.55, 1.05)):
        z = height_at(midpoint.x, midpoint.y) + rail_height
        rail = cube(f"{name}_Rail_{rail_index}", (midpoint.x, midpoint.y, z), (length * 0.5, .075, .075), mat, collection, .035)
        rail.rotation_euler[2] = angle


def setup_atmospheric_compositor(scene):
    """Add restrained depth haze so the large world reads with real scale."""
    scene.view_layers[0].use_pass_mist = True
    scene.world.mist_settings.start = 48.0
    scene.world.mist_settings.depth = 175.0
    scene.world.mist_settings.falloff = "QUADRATIC"
    scene.use_nodes = True
    nodes, links = scene.node_tree.nodes, scene.node_tree.links
    nodes.clear()
    layers = nodes.new("CompositorNodeRLayers")
    haze_amount = nodes.new("CompositorNodeMath")
    haze_amount.operation = "MULTIPLY"
    haze_amount.inputs[1].default_value = 0.16
    links.new(layers.outputs["Mist"], haze_amount.inputs[0])
    haze_color = nodes.new("CompositorNodeRGB")
    haze_color.outputs[0].default_value = (0.23, 0.31, 0.36, 1.0)
    mix = nodes.new("CompositorNodeMixRGB")
    mix.blend_type = "MIX"
    links.new(haze_amount.outputs[0], mix.inputs["Fac"])
    links.new(layers.outputs["Image"], mix.inputs[1])
    links.new(haze_color.outputs[0], mix.inputs[2])
    composite = nodes.new("CompositorNodeComposite")
    links.new(mix.outputs[0], composite.inputs["Image"])


def look_at(obj, target):
    obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()


def create_layout_image(path, extent, size=512):
    image=bpy.data.images.new("Semantic_Layout",width=size,height=size)
    colors={"river":(0.031,0.212,0.393,1),"village":(.485,.313,.117,1),"forest":(.031,.105,.038,1),"highlands":(.184,.174,.155,1),"meadow":(.153,.292,.068,1)}
    pixels=[]
    for iy in range(size):
        y=-extent/2+extent*iy/(size-1)
        for ix in range(size):
            x=-extent/2+extent*ix/(size-1)
            pixels.extend(colors[region_at(x,y)])
    image.pixels.foreach_set(pixels); image.filepath_raw=str(path); image.file_format="PNG"; image.save()


def main():
    args=parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    plan=json.loads(args.plan.read_text())
    random.seed(plan["seed"])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene=bpy.context.scene
    scene.world=bpy.data.worlds.new("WorldClaw_Atmosphere")
    scene.render.engine="CYCLES" if args.engine == "cycles" else "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x=plan["render"]["width"]; scene.render.resolution_y=plan["render"]["height"]; scene.render.resolution_percentage=max(10, min(100, args.resolution_percent))
    if args.engine == "cycles":
        scene.cycles.device = "GPU"
        scene.cycles.samples = args.samples or plan["render"].get("cycles_samples", 64)
        scene.cycles.use_denoising = True
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = backend
                prefs.get_devices()
                for device in prefs.devices:
                    device.use = device.type != "CPU"
                if any(device.use for device in prefs.devices):
                    break
            except (TypeError, RuntimeError):
                continue
    else:
        scene.eevee.taa_render_samples = args.samples or plan["render"].get("samples", 128)
    scene.render.image_settings.file_format="PNG"; scene.render.film_transparent=False
    scene.view_settings.look="AgX - Medium High Contrast"
    scene.view_settings.exposure = 0.42
    scene.world.color=(.035,.055,.08)
    mats={
      "river":material("Riverbed",(.16,.27,.25)), "village":material("VillageGround",(.33,.29,.16)),
      "forest":material("ForestFloor",(.09,.22,.08)), "highlands":material("HighlandRock",(.29,.28,.25)),
      "meadow":material("MeadowGrass",(.24,.43,.13)), "water":material("RiverWater",(.012,.12,.16),.03,.16),
      "wood":material("AgedTimber",(.18,.075,.028)), "pine":material("PineNeedles",(.025,.16,.055)),
      "plaster":material("WarmPlaster",(.48,.34,.20)), "roof":material("SlateRoof",(.10,.12,.13),.1,.55),
      "rock":material("WeatheredRock",(.31,.30,.27)), "stone":material("CutStone",(.34,.33,.30)),
      "path":material("PackedEarthFallback",(.12,.075,.035)),
    }
    collections={}
    for name in ("00_Terrain","10_Water","20_Village","30_Vegetation","40_Landmarks","90_Lighting"):
        c=bpy.data.collections.new(name); scene.collection.children.link(c); collections[name]=c
    project_root = Path(__file__).resolve().parent.parent
    asset_dir = (args.asset_dir or project_root / "assets/generated").resolve()
    terrain_mat = terrain_pbr_material(project_root)
    path_scan_root = project_root / "assets/external/polyhaven/materials/forest_ground_04"
    if path_scan_root.exists():
        mats["path"] = scanned_surface_material("Packed_Earth_Gravel_PBR", path_scan_root, 16.0)
    mountains_mat = mountain_material()
    asset_paths = {
        "watchtower": asset_dir / "watchtower_pbr.glb",
        "cottage": asset_dir / "cottage_pbr.glb",
        "cottage_stone": asset_dir / "cottage_stone_pbr.glb",
        "bridge": asset_dir / "bridge_pbr.glb",
        "windmill": asset_dir / "windmill_pbr.glb",
        # Fine foliage is a poor single-image reconstruction target: the
        # Hunyuan result becomes a billboard. Use the vetted CC0 tree instead.
        "pine": asset_dir / "pine_cc0.glb",
        "pine_grove": project_root / "assets/external/polyhaven/pine_sapling_small/pine_sapling_small_1k.gltf",
        "fir_tree": project_root / "assets/external/polyhaven/fir_tree_01/fir_tree_01_1k.gltf",
        "grass": project_root / "assets/external/polyhaven/grass_medium_01/grass_medium_01_1k.gltf",
        "boulder": project_root / "assets/external/polyhaven/boulder_01/boulder_01_1k.gltf",
    }
    templates = {
        key: load_asset_template(path, key)
        for key, path in asset_paths.items() if path.exists()
    }
    for key in ("pine", "pine_grove"):
        if templates.get(key):
            tint_template_materials(templates[key], (0.63, 0.82, 0.56), 0.22)
    if templates.get("fir_tree"):
        tint_template_materials(templates["fir_tree"], (0.48, 0.67, 0.42), 0.32)
    if templates.get("boulder"):
        tint_template_materials(templates["boulder"], (0.42, 0.47, 0.49), 0.78, "COLOR")
    create_backdrop(mats["highlands"], collections["00_Terrain"])
    create_terrain(plan,terrain_mat,collections["00_Terrain"])
    create_mountain_ranges(mountains_mat, collections["00_Terrain"])
    create_water(mats["water"],collections["10_Water"])
    bridge_y = 7 * math.sin(7 / 31) - 2
    if templates.get("bridge"):
        place_asset(templates["bridge"], "Hunyuan_Bridge", 7, bridge_y, math.pi/2, 14.5, collections["40_Landmarks"], "extent")
    else:
        create_bridge(mats,collections["40_Landmarks"])
    create_stone_circle(mats,collections["40_Landmarks"])
    used_hunyuan = False
    if templates.get("watchtower"):
        place_asset(templates["watchtower"], "Hunyuan_Watchtower", -36, 38, -.35, 12.5, collections["40_Landmarks"])
        used_hunyuan = True
    elif args.asset and args.asset.exists():
        used_hunyuan = bool(import_generated_asset(args.asset,mats,collections["40_Landmarks"]))
    if not used_hunyuan: create_procedural_tower(mats,collections["40_Landmarks"])
    if templates.get("windmill"):
        place_asset(templates["windmill"], "Hunyuan_Windmill", 47, 40, .55, 12.5, collections["40_Landmarks"])
    houses=[(19,20,.12),(26,15,-.34),(34,18,.38),(23,29,-.46),(32,29,.52),(39,24,-.18),(27,38,.24),(14,31,-.58),(38,36,.66)]
    for i,(x,y,r) in enumerate(houses):
        house_template = templates.get("cottage_stone") if i in (1, 4, 7) else templates.get("cottage")
        if house_template:
            root = place_asset(house_template, f"Hunyuan_Cottage_{i:02d}", x, y, r, random.uniform(5.9, 7.5), collections["20_Village"])
            root.scale.x *= random.uniform(0.92, 1.08)
            root.scale.y *= random.uniform(0.92, 1.08)
        else:
            create_house(f"VillageHouse_{i:02d}",x,y,r,mats,collections["20_Village"],random.uniform(.82,1.12))
    make_path_ribbon("Village_Main_Path",[(7,0,0),(13,8,0),(18,15,0),(25,21,0),(32,25,0),(39,30,0)],mats["path"],collections["20_Village"],1.0)
    make_path_ribbon("Village_North_Path",[(26,21,0),(24,29,0),(27,38,0)],mats["path"],collections["20_Village"],0.72,9)
    make_path_ribbon("Village_East_Path",[(29,24,0),(35,20,0),(40,24,0)],mats["path"],collections["20_Village"],0.66,9)
    create_fence_line("West_Paddock", (12, 24, 0), (16, 38, 0), mats["wood"], collections["20_Village"], 8)
    create_fence_line("East_Paddock", (41, 18, 0), (46, 31, 0), mats["wood"], collections["20_Village"], 7)
    placed=0
    while placed<plan["density"]["trees"]:
        x=random.uniform(-84,84); y=random.uniform(-82,82); reg=region_at(x,y)
        if reg not in ("forest","meadow") or math.hypot(x-29,y-23)<24: continue
        if abs(y-(7*math.sin(x/31)-2))<12.5: continue
        if math.hypot(x+36,y-38)<13 or math.hypot(x-47,y-40)<14: continue
        if y < 8 and abs(x - (7.0 - 0.72 * y)) < 21.0: continue
        tree_scale = random.uniform(.82,1.35)
        roll = random.random()
        if templates.get("fir_tree") and roll < 0.19:
            pine_template = templates["fir_tree"]
        elif templates.get("pine_grove") and roll < 0.47:
            pine_template = templates["pine_grove"]
        else:
            pine_template = templates.get("pine")
        if pine_template:
            if pine_template is templates.get("fir_tree"):
                target_height = random.uniform(15.5, 22.0)
                width_min, width_max = .88, 1.12
            else:
                target_height = 10.8 * tree_scale
                width_min, width_max = 1.42, 1.92
            root = place_asset(pine_template, f"CC0_Pine_{placed:03d}", x, y, random.random()*math.tau, target_height, collections["30_Vegetation"])
            root.scale.x *= random.uniform(width_min, width_max)
            root.scale.y *= random.uniform(width_min, width_max)
            if pine_template is templates.get("fir_tree"):
                root.location.z -= random.uniform(.28, .48)
        else:
            create_tree(f"Pine_{placed:03d}",x,y,mats,collections["30_Vegetation"],tree_scale)
        placed+=1
    alpine_placed = 0
    while alpine_placed < plan["density"].get("alpine_trees", 34):
        x = random.uniform(-108, 108); y = random.uniform(67, 108)
        if math.hypot(x+36,y-38)<15 or math.hypot(x-47,y-40)<16:
            continue
        roll = random.random()
        alpine_template = templates.get("fir_tree") if roll < .48 else templates.get("pine_grove")
        if not alpine_template:
            break
        if alpine_template is templates.get("fir_tree"):
            target_height = random.uniform(12.0, 18.0)
            width = random.uniform(.82, 1.04)
        else:
            target_height = random.uniform(8.0, 12.5)
            width = random.uniform(1.25, 1.65)
        root = place_asset(alpine_template, f"Alpine_Conifer_{alpine_placed:03d}", x, y, random.random()*math.tau, target_height, collections["30_Vegetation"])
        root.scale.x *= width; root.scale.y *= width
        if alpine_template is templates.get("fir_tree"):
            root.location.z -= .36
        alpine_placed += 1
    if templates.get("grass"):
        grass_placed = 0
        while grass_placed < plan["density"].get("grass_patches", 86):
            x=random.uniform(-78,78); y=random.uniform(-70,75); reg=region_at(x,y)
            if reg not in ("meadow", "village") or abs(y-(7*math.sin(x/31)-2)) < 8.5:
                continue
            root = place_asset(templates["grass"], f"CC0_GrassPatch_{grass_placed:03d}", x, y, random.random()*math.tau, random.uniform(4.0,7.2), collections["30_Vegetation"], "extent")
            root.scale.z *= random.uniform(.9, 1.45)
            grass_placed += 1
    for i in range(plan["density"]["rocks"]):
        x=random.uniform(-86,86); y=random.choice((-1,1))*random.uniform(35,86); z=height_at(x,y)
        if templates.get("boulder"):
            root = place_asset(templates["boulder"], f"CC0_Boulder_{i:03d}", x, y, random.random()*math.tau, random.uniform(1.4,4.8), collections["30_Vegetation"], "extent")
            root.scale.x *= random.uniform(0.8, 1.5); root.scale.y *= random.uniform(0.75, 1.3); root.scale.z *= random.uniform(0.55, 1.05)
        else:
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=random.uniform(.5,1.8),location=(x,y,z+random.uniform(.2,.7)))
            o=bpy.context.object; o.name=f"Rock_{i:03d}"; o.scale=(1.6,1,.75); o.rotation_euler=[random.random()*2 for _ in range(3)]; o.data.materials.append(mats["rock"])
            for c in list(o.users_collection): c.objects.unlink(o)
            collections["30_Vegetation"].objects.link(o)
    if templates.get("boulder"):
        for landmark, (cx, cy, count, radius) in {
            "Tower": (-36, 38, 28, 13.0),
            "Windmill": (47, 40, 18, 11.0),
        }.items():
            for i in range(count):
                angle = random.random() * math.tau
                distance = radius * math.sqrt(random.uniform(.22, 1.0))
                x = cx + math.cos(angle) * distance; y = cy + math.sin(angle) * distance
                root = place_asset(templates["boulder"], f"{landmark}_Rock_{i:02d}", x, y, random.random()*math.tau, random.uniform(.85, 3.4), collections["40_Landmarks"], "extent")
                root.scale.x *= random.uniform(.75, 1.35); root.scale.y *= random.uniform(.7, 1.3); root.scale.z *= random.uniform(.55, .95)
        for i in range(plan["density"].get("river_rocks", 115)):
            x = random.uniform(-79, 79)
            center_y = 7 * math.sin(x / 31) - 2
            y = center_y + random.choice((-1, 1)) * random.uniform(5.4, 10.8)
            root = place_asset(templates["boulder"], f"Riverbank_Stone_{i:03d}", x, y, random.random()*math.tau, random.uniform(.65, 2.65), collections["10_Water"], "extent")
            root.scale.x *= random.uniform(.72, 1.4); root.scale.y *= random.uniform(.65, 1.25); root.scale.z *= random.uniform(.55, .95)
    bpy.ops.object.light_add(type="SUN",location=(20,-30,80)); sun=bpy.context.object; sun.name="Golden_Hour_Sun"; sun.data.energy=2.65; sun.data.color=(1.0,.78,.56); sun.data.angle=math.radians(3.2); sun.rotation_euler=(math.radians(34),math.radians(-16),math.radians(-38))
    bpy.ops.object.light_add(type="AREA",location=(-35,-20,55)); area=bpy.context.object; area.name="Sky_Fill"; area.data.energy=900; area.data.shape="DISK"; area.data.size=55; look_at(area,(0,0,0))
    scene.world.use_nodes=True; bg=scene.world.node_tree.nodes.get("Background")
    hdri_path = project_root / "assets/external/polyhaven/hdri/hilly_terrain_01_puresky/hilly_terrain_01_puresky_2k.hdr"
    if hdri_path.exists():
        bg.inputs["Strength"].default_value = .42
        world_nodes = scene.world.node_tree.nodes
        coord = world_nodes.new("ShaderNodeTexCoord")
        mapping = world_nodes.new("ShaderNodeMapping")
        mapping.inputs["Rotation"].default_value[2] = math.radians(128)
        environment = world_nodes.new("ShaderNodeTexEnvironment")
        environment.image = bpy.data.images.load(str(hdri_path), check_existing=True)
        scene.world.node_tree.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        scene.world.node_tree.links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
        scene.world.node_tree.links.new(environment.outputs["Color"], bg.inputs["Color"])
    else:
        bg.inputs["Strength"].default_value=.22
        sky = scene.world.node_tree.nodes.new("ShaderNodeTexSky")
        sky.sky_type = "NISHITA"; sky.sun_elevation = math.radians(18); sky.sun_rotation = math.radians(224)
        sky.altitude = .35; sky.air_density = 1.25; sky.dust_density = 2.2
        scene.world.node_tree.links.new(sky.outputs["Color"], bg.inputs["Color"])
    setup_atmospheric_compositor(scene)
    cams=[
        ("global",(95,-125,54),(7,25,27.0),48),
        ("walk_village",(-1,-10,16),(29,24,4.6),55),
        ("walk_river",(42,-48,15),(7,1,2.4),50),
        ("tower_close",(-8,10,30),(-36,38,height_at(-36,38)+6.2),44),
    ]
    rendered = []
    for name,loc,target,lens in cams:
        if args.camera == "details" and name not in ("walk_river", "tower_close"):
            continue
        if args.camera not in ("all", "details") and args.camera != name:
            continue
        bpy.ops.object.camera_add(location=loc); cam=bpy.context.object; cam.name="Camera_"+name; cam.data.lens=lens; look_at(cam,target); scene.camera=cam
        scene.render.filepath=str(args.output/(name+".png")); bpy.ops.render.render(write_still=True); rendered.append(name + ".png")
    create_layout_image(args.output/"semantic_layout.png",plan["world"]["extent_m"])
    # Template objects are only import-time sources; linked scene instances
    # retain their meshes and materials after these hidden originals are gone.
    for template in templates.values():
        for obj in template["objects"]:
            bpy.data.objects.remove(obj, do_unlink=True)
    outputs = ["semantic_layout.png"] + rendered
    if not args.skip_export:
        bpy.ops.wm.save_as_mainfile(filepath=str(args.output/"world.blend"))
        bpy.ops.export_scene.gltf(filepath=str(args.output/"world.glb"),export_format="GLB",export_cameras=False,export_lights=False)
        outputs[:0] = ["world.blend", "world.glb"]
    manifest={"name":plan["world"]["name"],"seed":plan["seed"],"hunyuan_asset_used":used_hunyuan,"pbr_asset_types":sorted(templates),"terrain_material":"continuous_cc0_pbr","distant_mountain_ranges":2,"hdri_environment":hdri_path.name if hdri_path.exists() else None,"render_engine":args.engine,"objects":len(bpy.data.objects),"meshes":len(bpy.data.meshes),"outputs":outputs}
    (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps(manifest))


if __name__=="__main__": main()
