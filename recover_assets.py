"""Recover static native assemblies and remaining meshes into one OBJ gallery."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import struct
from overboard_native import NativeArchive, require, u16, u32, validate_obj


def asset_label(block, ref, assembly=False):
    """Descriptive visual labels; unknown identities retain a stable source name."""
    shapes = {130:'Emplacement',161:'Native_Helper',189:'Small_Sailing_Ship',216:'Sailing_Ship',
              228:'Lock_Gate',286:'Flagpole',301:'Tower',1066:'Player_Ship',1474:'Floating_Device',
              2249:'Sailing_Ship',2274:'Balloon',2341:'Balloon',2386:'Large_Sailing_Ship',
              2446:'Sailing_Ship',2466:'Vehicle',2522:'Giant_Crayfish',2586:'Windmill',2628:'Balloon',
              2631:'Paddle_Boat',2643:'Drill_Device',2716:'Sailing_Ship',2723:'Sailing_Ship',
              2742:'Tower',2770:'Tower',2788:'Sailing_Ship',2827:'Sailing_Ship',3003:'Submarine',
              3127:'Large_Tower',3129:'Lift_Platform',3265:'Mechanism',3498:'Sailing_Ship',
              3553:'Ice_Tower',3556:'Whirlpool',3586:'Sailing_Ship',3605:'Dragon',4043:'Large_Structure',
              4045:'Creature_Section',4154:'Tower',4669:'Character',4671:'Shark'}
    meshes = {38:'Sphere',39:'Barrel',40:'Wireframe_Barrel',41:'Cannonball',42:'Spikes',
              43:'Character_Sprite',44:'Skull_Sprite',45:'Wireframe_Pickup',46:'Rock_Cluster',
              47:'Treasure_Chest',48:'Ship_Pickup',49:'Flame_Pickup',50:'Winged_Pickup',
              51:'Cannon_Pickup',52:'Lightning_Pickup',53:'Spiked_Mine',54:'Rocket_Pickup',
              55:'Shell_Pickup',56:'Broadside_Pickup',57:'Steering_Wheel_Pickup',
              58:'Supply_Crate',59:'Supply_Crate',60:'Supply_Crate',61:'Supply_Crate',62:'Supply_Crate',
              63:'Health_Crate',133:'Tower_Base',162:'Stone_Tower_Base',178:'Iceberg',201:'Building',
              202:'Roof_Rubble',229:'Tower_Base',255:'Vortex_Sprite',260:'Barrel_Emplacement',270:'Bottle',
              275:'Gate_Leaf',283:'Gate_Panel',284:'Gate_Leaf',285:'Gate_Panel',289:'Skull_Sprite',
              310:'Goal_Marker_Green',311:'Goal_Marker_Red',326:'Hatch_Platform',327:'Damaged_Hatch_Platform',
              340:'Palm_Tree',341:'Palm_Tree_Cluster',348:'Potted_Palm',373:'Red_Herring_Sign',
              374:'Red_Herring_Sign',375:'Red_Herring_Sign'}
    if assembly:
        label = 'Treasure_Chest' if 4769 <= ref <= 4779 and block in (22,23) else shapes.get(ref,'Native_Assembly')
        return f'{label}_b{block:02d}_shape_{ref:05d}'
    common = block < 20 or 27 <= block <= 37
    label = meshes.get(ref,'Unidentified_Mesh') if common else 'Unidentified_Mesh'
    if common and 418 <= ref <= 621:
        label = 'Effect_Sprite'
    return f'{label}_b{block:02d}_resource_{ref:05d}'


def multiply(a, b):
    return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def artic_transforms(data):
    require(len(data) % 40 == 0, 'Invalid articulation record count')
    out, stack = {}, []
    for at in range(0, len(data), 40):
        ident, children = struct.unpack_from('<2I', data, at)
        require(u16(data, at+8) == 0x5858, 'Invalid articulation matrix tag')
        m = struct.unpack_from('<9h', data, at+10)
        t = struct.unpack_from('<3i', data, at+28)
        matrix = [[m[i*3+j]/16384 for j in range(3)]+[t[i]] for i in range(3)]+[[0, 0, 0, 1]]
        while stack and stack[-1][1] == 0:
            stack.pop()
        if stack:
            stack[-1][1] -= 1
            matrix = multiply(stack[-1][0], matrix)
        require(ident not in out, 'Duplicate articulation node')
        out[ident] = matrix
        if children:
            stack.append([matrix, children])
    require(all(left == 0 for _, left in stack), 'Incomplete articulation hierarchy')
    return out


def assemble(archive, block, shape, artic):
    transforms = artic_transforms(archive.payload(block, artic))
    sh = archive.payload(block, shape)
    vertices, faces, components = [], [], set()
    require(len(sh) % 20 == 0, 'Invalid shape record count')
    for at in range(0, len(sh), 20):
        ident, n, art, geo, shader = struct.unpack_from('<5I', sh, at)
        require(art in transforms, 'Shape refers to missing articulation node')
        vv, ff, scale = archive.mesh(block, geo)
        T = transforms[art]
        off = len(vertices)
        for v in vv:
            v = [c*scale/256 for c in v]+[1]
            p = [sum(T[i][k]*v[k] for k in range(4)) for i in range(3)]
            vertices.append((p[0], p[1], -p[2]))
        for ids, uv, tex, rgb, op in ff:
            faces.append(([i+off for i in ids], uv, tex, rgb, op))
        components.add(geo)
    return vertices, faces, components


def recover_assets(archive, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    texture_folder = destination/'textures'
    texture_folder.mkdir(exist_ok=True)
    texture_digests = {}
    def tex_digest(b, ref):
        key = b, ref
        if key not in texture_digests:
            d = archive.payload(b, ref)
            pr, ir = struct.unpack_from('<2I', d, 16)
            texture_digests[key] = hashlib.sha256(d[:16]+archive.payload(b, pr)+archive.payload(b, ir)).hexdigest()
        return texture_digests[key]
    def signature(b, vertices, faces):
        appearance = [(ids, uv, tex_digest(b, tex) if tex is not None else None, rgb, op)
                      for ids, uv, tex, rgb, op in faces]
        return hashlib.sha256(json.dumps(([[round(c, 5) for c in v] for v in vertices], appearance),
                                       separators=(',', ':')).encode()).hexdigest()
    terrain = set()
    for b, bb in archive.blocks.items():
        for ref, r in bb['resources'].items():
            if r['type'] != 0x271:
                continue
            for x, z, tile, rot, y, refs, pitch in archive.cells(b, int(ref)):
                for geo in refs:
                    if geo:
                        terrain.add((b, geo))
    assets, component_keys, seen, unresolved = [], set(), set(), []
    for b, bb in archive.blocks.items():
        artics = {}
        for ref, r in bb['resources'].items():
            if r['type'] == 0x86:
                try:
                    artics[int(ref)] = set(artic_transforms(archive.payload(b, int(ref))))
                except (ValueError, struct.error):
                    continue
        for sr, r in bb['resources'].items():
            if r['type'] != 0x87:
                continue
            shape = int(sr)
            sh = archive.payload(b, shape)
            if len(sh) % 20:
                continue
            ids = {u32(sh, j+8) for j in range(0, len(sh), 20)}
            candidates = [a for a, nodes in artics.items() if ids <= nodes]
            # Node identities validate the pairing; adjacency only resolves reused trivial roots.
            candidates.sort(key=lambda a:(abs(a-shape), a))
            if not candidates:
                unresolved.append((b, shape, 'No matching native articulation; component meshes retained'))
                continue
            try:
                vv, ff, components = assemble(archive, b, shape, candidates[0])
                visible = [f for f in ff if f[4] & 128 or f[4] == 2]
                helper = [f for f in ff if not(f[4] & 128 or f[4] == 2)]
                sig = signature(b, vv, visible)
                for ref in components:
                    mv, mf, sc = archive.mesh(b, ref)
                    component_keys.add(signature(b, mv, mf))
                if sig in seen:
                    continue
                seen.add(sig)
                assets.append((asset_label(b, shape, True), b, vv, visible, helper))
            except (ValueError, KeyError, struct.error) as e:
                unresolved.append((b, shape, str(e)))
    nonmesh = set()
    standalone_seen = set()
    for b, bb in archive.blocks.items():
        for rr, r in bb['resources'].items():
            if r['type'] not in (0x40, 0x41):
                continue
            ref = int(rr)
            if (b, ref) in terrain:
                continue
            try:
                vv, ff, scale = archive.mesh(b, ref)
            except (ValueError, struct.error, IndexError):
                # Type 0x40 also stores fonts and other 2D data; these are not meshes.
                candidate = archive.payload(b, ref)
                if len(candidate) >= 60 and u16(candidate, 2) == 0x8001:
                    raise
                nonmesh.add(hashlib.sha256(archive.payload(b, ref)).digest())
                continue
            sig = signature(b, vv, ff)
            if sig in component_keys or sig in standalone_seen:
                continue
            standalone_seen.add(sig)
            vv = [(x*scale/256, y*scale/256, -z*scale/256) for x, y, z in vv]
            visible = [f for f in ff if f[4] & 128 or f[4] == 2]
            helper = [f for f in ff if not(f[4] & 128 or f[4] == 2)]
            assets.append((asset_label(b, ref), b, vv, visible, helper))
    name = 'Overboard_Recovered_Assets'
    obj_path, mtl_path = destination/(name+'.obj'), destination/(name+'.mtl')
    mats, material_lines, texture_names = {}, [], {}
    # Deduplicated materials use texture bytes, never a nearest-image guess.
    def material(b, face):
        ids, uv, tex, rgb, op = face
        key = ('texture', tex_digest(b, tex)) if tex is not None else ('colour', rgb)
        if key not in mats:
            mat = f'Material_{len(mats):04d}'
            mats[key] = mat
            material_lines.append('newmtl '+mat)
            if tex is not None:
                # Prefix by block to prevent equal resource numbers from overwriting different art.
                temporary = texture_folder/f'b{b:02d}'
                temporary.mkdir(exist_ok=True)
                filename, alpha = archive.texture(b, tex, temporary, destination/'Native_Animation_Frames'/f'b{b:02d}')
                target = texture_folder/(f'b{b:02d}_'+filename)
                (temporary/filename).replace(target)
                temporary.rmdir()
                material_lines.extend(('Kd 1 1 1', 'map_Kd textures/'+target.name))
                if alpha:
                    material_lines.append('map_d -imfchan a textures/'+target.name)
            else:
                material_lines.append('Kd '+' '.join(f'{min(1,c/63):.8f}' for c in rgb))
            material_lines.extend(('Ks 0 0 0','illum 1',''))
        return mats[key]
    off = uv_off = total_faces = total_helpers = 0
    x_cursor = z_cursor = row_depth = 0.
    gallery = []
    with obj_path.open('w', encoding='utf-8', newline='\n') as obj:
        obj.write(f'mtllib {name}.mtl\n')
        for index, (label, b, vv, visible, helpers) in enumerate(assets):
            if not vv:
                continue
            lo = [min(v[k] for v in vv) for k in range(3)]
            hi = [max(v[k] for v in vv) for k in range(3)]
            width, depth = max(hi[0]-lo[0], 1000.), max(hi[2]-lo[2], 1000.)
            if index and index % 12 == 0:
                x_cursor = 0.
                z_cursor += row_depth+1500
                row_depth = 0.
            shift = [x_cursor-lo[0], -lo[1], z_cursor-lo[2]]
            for v in vv:
                obj.write('v '+' '.join(f'{v[k]+shift[k]:.8f}' for k in range(3))+'\n')
            for suffix, faces in (('', visible), ('_Native_Helpers', helpers)):
                if not faces:
                    continue
                obj.write('o '+label+suffix+'\n')
                for face in faces:
                    ids, uv, tex, rgb, op = face
                    obj.write('usemtl '+material(b, face)+'\n')
                    if len(ids) < 3:
                        obj.write('p '+' '.join(str(i+off+1) for i in ids)+'\n')
                    elif uv is not None:
                        for u, v in uv:
                            obj.write(f'vt {u/255:.9f} {1-v/255:.9f}\n')
                        obj.write('f '+' '.join(f'{i+off+1}/{uv_off+j+1}' for j, i in enumerate(ids))+'\n')
                        uv_off += len(uv)
                    else:
                        obj.write('f '+' '.join(str(i+off+1) for i in ids)+'\n')
                    total_faces += len(ids) >= 3
                    total_helpers += bool(suffix)
            gallery.append((label, b, vv, visible, helpers, shift))
            off += len(vv)
            x_cursor += width+1500
            row_depth = max(row_depth, depth)
    mtl_path.write_text('\n'.join(material_lines)+'\n', encoding='utf-8')
    validate_obj(obj_path)
    print(f'Asset gallery: {len(assets)} assets, {total_faces} polygons, {off} vertices; {len(unresolved)} assembly records require component-only recovery', flush=True)
    return gallery, unresolved


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('unpacked_directory')
    parser.add_argument('output_directory')
    args = parser.parse_args()
    recover_assets(NativeArchive(args.unpacked_directory), args.output_directory)
