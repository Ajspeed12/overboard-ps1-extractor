"""Native PS1 Shipwreckers/Overboard archive and static environment decoder.

No capture geometry or textures are used. Tested against SLUS_005.58 data.
Resource numbers here are the actual table slots (older research used slot-4).
"""
from pathlib import Path
import hashlib
import json
import struct
from collections import Counter
from functools import lru_cache


def u16(data, offset=0):
    return struct.unpack_from('<H', data, offset)[0]


def u32(data, offset=0):
    return struct.unpack_from('<I', data, offset)[0]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unpack_archive(source, destination):
    """Unpack declared payload bytes, excluding relocation trailers and headers."""
    source, destination = Path(source), Path(destination)
    files = {p.name.upper(): p for p in source.iterdir() if p.is_file()}
    for name in ('RES.RDR', 'RES.RDA', 'RES.RDT'):
        require(name in files, f'Missing {name} in {source}')
    rdr, rda, rdt = (files[n].read_bytes() for n in ('RES.RDR', 'RES.RDA', 'RES.RDT'))
    require(rdr[:4] == b'RDR2' and rda[:4] == b'RDA2', 'Not an RDR2/RDA2 archive')
    require(u32(rdr, 8) == 1 and rdr[12:20].rstrip(b'\0').upper() == b'RES.RDT',
            'This extractor supports the single RES.RDT PS1 archive')
    count = u32(rda, 8)
    require(16 + count * 4 <= len(rda), 'RDA resource table exceeds file')
    starts = {20}
    for j in range(count):
        word = u32(rda, 16 + j * 4)
        offset = (word >> 4) + 20
        if word & 15 == 5 and offset < len(rdt) and rdt[offset:offset+4] == b'RDA2':
            starts.add(offset)
    starts = sorted(starts)
    require(starts and rdt[20:24] == b'RDA2', 'No native resource blocks found')
    manifest = {'format': 'overboard-native-unpack-1', 'sources': {}, 'blocks': []}
    for name, contents in (('RES.RDR', rdr), ('RES.RDA', rda), ('RES.RDT', rdt)):
        manifest['sources'][name] = hashlib.sha256(contents).hexdigest()
    destination.mkdir(parents=True, exist_ok=True)
    total = 0
    for b, start in enumerate(starts):
        end = starts[b+1] if b+1 < len(starts) else len(rdt)
        n = u32(rdt, start+8)
        require(start+16+n*4 <= end, f'Block {b}: invalid table length')
        resources = {}
        folder = destination / f'block_{b:02d}'
        folder.mkdir(exist_ok=True)
        for ref in range(n):
            word = u32(rdt, start+16+ref*4)
            if word & 15 != 5:
                continue
            offset = (word >> 4) + 20
            require(start+16+n*4 <= offset-20 < end, f'Block {b}, resource {ref}: invalid pointer')
            size, kind = u32(rdt, offset-16), u16(rdt, offset-6)
            require(offset+size <= end, f'Block {b}, resource {ref}: invalid payload length')
            name = f'resource_{ref:05d}_type_{kind:04x}.bin'
            (folder / name).write_bytes(rdt[offset:offset+size])
            resources[str(ref)] = {'type': kind, 'file': name, 'size': size}
            total += 1
        manifest['blocks'].append({'id': b, 'folder': folder.name, 'resources': resources})
    (destination / 'archive_index.json').write_text(json.dumps(manifest, separators=(',', ':')), encoding='utf-8')
    print(f'Unpacked {len(starts)} blocks / {total} resources into {destination}', flush=True)
    return manifest


class NativeArchive:
    def __init__(self, folder):
        self.folder = Path(folder)
        index = json.loads((self.folder / 'archive_index.json').read_text(encoding='utf-8'))
        require(index.get('format') == 'overboard-native-unpack-1', 'Unsupported unpacked archive')
        self.blocks = {b['id']: b for b in index['blocks']}

    def kind(self, block, ref):
        return self.blocks[block]['resources'][str(ref)]['type']

    @lru_cache(maxsize=None)
    def payload(self, block, ref):
        b = self.blocks[block]
        r = b['resources'][str(ref)]
        data = (self.folder / b['folder'] / r['file']).read_bytes()
        require(len(data) == r['size'], f'Truncated resource {block}/{ref}')
        return data

    def campaign_maps(self):
        maps = []
        # The first 20 native blocks are the five campaign regions, four stages each.
        # Later map resources include multiplayer arenas and are deliberately excluded.
        for b in range(20):
            require(b in self.blocks, f'Campaign block {b} is absent')
            refs = [int(r) for r, v in self.blocks[b]['resources'].items() if v['type'] == 0x271]
            require(len(refs) == 1, f'Block {b}: expected one campaign map, found {len(refs)}')
            maps.append((b, refs[0]))
        return maps

    def cells(self, block, map_ref):
        d = self.payload(block, map_ref)
        pitch = u32(d)
        width, height = struct.unpack_from('<2H', d, 4)
        p = struct.unpack_from('<5I', d, 12)
        require(pitch > 0 and width > 0 and height > 0, 'Invalid map dimensions')
        require(all(32 <= x < len(d) for x in p), 'Invalid map section pointer')
        for z in range(height*16):
            for x in range(width*16):
                coarse = u16(d, p[0]+2*((z//16)*width+x//16)) & 0xfff0
                # Zero entries select a constant default cell, as in SLUS_005.58.
                mid_at = p[1]+coarse*2+2*(((z//4)%4)*4+(x//4)%4) if coarse else p[1]
                middle = u16(d, mid_at) & 0xfff0
                cell_at = p[2]+middle*4+4*((z%4)*4+x%4) if middle else p[2]
                word = u32(d, cell_at)
                tile, flags = word & 255, word >> 16
                signed = flags if flags < 32768 else flags-65536
                height_y = (signed & ~3)*4
                at = p[3]+tile*24
                require(at+24 <= p[4], f'Block {block}: tile {tile} is outside tile table')
                geos = struct.unpack_from('<3I', d, at)
                yield x, z, tile, flags & 3, height_y, geos, pitch

    @lru_cache(maxsize=None)
    def mesh(self, block, ref):
        d = self.payload(block, ref)
        require(self.kind(block, ref) in (0x40, 0x41), f'{block}/{ref}: unexpected mesh resource type')
        scale, nv, ne, nf = struct.unpack_from('<4H', d, 8)
        p = struct.unpack_from('<7I', d, 32)
        require(all(60 <= x <= len(d) for x in p), f'{block}/{ref}: invalid mesh pointers')
        require(p[0]+nv*8 <= p[1] and p[1]+ne*4 <= p[2] and p[5]+nf*4 <= p[6],
                f'{block}/{ref}: mesh arrays overlap')
        vertices = [struct.unpack_from('<3h', d, p[0]+j*8) for j in range(nv)]
        edges = [struct.unpack_from('<2H', d, p[1]+j*4) for j in range(ne)]
        require(all(a < nv and b < nv for a, b in edges), 'Mesh edge index exceeds vertex count')
        faces = []
        for j in range(nf):
            s = u32(d, p[5]+j*4)
            require(p[2] <= s < p[3], 'Face lies outside polygon section')
            op, flags, n = struct.unpack_from('<BBH', d, s)
            require(op in (0x81, 0x82, 0x84, 0x02, 0x01, 0x04), f'{block}/{ref}: unsupported polygon opcode {op:#x}')
            ids = [q & 0x3fff for q in struct.unpack_from('<'+'H'*n, d, s+4)]
            require(all(q < ne for q in ids), 'Polygon edge index exceeds edge count')
            ee = [edges[q] for q in ids]
            if n < 3:
                require(n == 2 and ee[0] == ee[1] and ee[0][0] == ee[0][1], 'Unrecognised degenerate primitive')
                vs = [ee[0][0]]
            else:
                a, b = ee[0]
                vs = [a, b] if b in ee[1] else [b, a]
                for a, b in ee[1:]:
                    require(vs[-1] in (a, b), 'Polygon edges do not form a loop')
                    vs.append(b if vs[-1] == a else a)
                require(vs[-1] == vs[0], 'Polygon edge loop does not close')
                vs.pop()
                direct = list(struct.unpack_from('<'+'H'*n, d, s+4+2*n))
                require(direct == vs, 'Native vertex list disagrees with the polygon edge loop')
            uv, tex = None, None
            if op in (0x82, 0x02):
                tex = u32(d, s+4+4*n)
                rgb = tuple(d[s+8+4*n:s+11+4*n])
                uv = [struct.unpack_from('<2H', d, s+12+4*n+k*4) for k in range(n)]
                descriptor = self.payload(block, tex)
                if u16(descriptor, 6) & 2:
                    # Transposed texture coordinates: independently checked against
                    # native descriptor flags and matching DuckStation surface UVs.
                    uv = [(v, u) for u, v in uv]
            else:
                rgb = tuple(d[s+4+4*n:s+7+4*n])
            # Apply the validated handedness conversion once, preserving vertex/UV association.
            faces.append((vs[::-1], uv[::-1] if uv is not None else None, tex, rgb, op))
        return vertices, faces, scale

    def placed_environment(self, block, map_ref, repair=True):
        """Recover tile cut planes within source fixed-point quantisation error.

        Only tile-boundary coordinates are projected onto authored half-pitch
        planes. Interior geometry and deliberate overlaps remain untouched.
        Matching points across neighbouring tiles share a consensus position;
        vertex indices, face divisions, and UV seams are never welded.
        """
        placements = []
        points, candidates = [], {}
        for x, z, tile, rot, y, geos, pitch in self.cells(block, map_ref):
            for layer, ref in enumerate(geos):
                if not ref:
                    continue
                vertices, faces, scale = self.mesh(block, ref)
                off = len(points)
                for vx, vy, vz in vertices:
                    rx, rz = ((vx, vz), (vz, -vx), (-vx, -vz), (-vz, vx))[rot]
                    xyz = [rx*scale/256+x*pitch, vy*scale/256+(0 if layer == 2 else y), -rz*scale/256+z*pitch]
                    if repair:
                        for axis, raw, grid in ((0, rx, x), (2, -rz, z)):
                            local = raw*scale/256
                            # Error bound for integer scale and quantised vertex components.
                            tolerance = min(20., abs(raw)/256+scale/256+1)
                            if abs(abs(local)-pitch/2) <= tolerance:
                                side = 1 if local > 0 else -1
                                plane = 2*grid+side
                                xyz[axis] = plane*pitch/2
                                candidates.setdefault((layer, axis, plane), []).append((len(points), x, z, tolerance))
                    points.append(xyz)
                placements.append((x, z, layer, ref, off, len(vertices)))
        parent = list(range(len(points)))
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        joined = 0
        for (layer, axis, plane), entries in candidates.items():
            owners = {}
            for entry in entries:
                owners.setdefault(entry[1:3], []).append(entry)
            for owner, left in owners.items():
                other = (owner[0]+1, owner[1]) if axis == 0 else (owner[0], owner[1]+1)
                if other not in owners:
                    continue
                right = owners[other]
                def nearest(a, pool):
                    return min(pool, key=lambda b:sum((points[a[0]][k]-points[b[0]][k])**2 for k in range(3)))
                for a in left:
                    b = nearest(a, right)
                    reverse = nearest(b, left)
                    # Duplicate authored vertices are allowed to join their common endpoint.
                    if any(abs(points[reverse[0]][k]-points[a[0]][k]) > 1e-7 for k in range(3)):
                        continue
                    bound = min(24., a[3]+b[3]+1)
                    if all(abs(points[a[0]][k]-points[b[0]][k]) <= bound for k in range(3)):
                        ia, ib = find(a[0]), find(b[0])
                        if ia != ib:
                            parent[ib] = ia
                            joined += 1
        groups = {}
        for j in range(len(points)):
            r = find(j)
            if r != j:
                groups.setdefault(r, [r]).append(j)
        for ids in groups.values():
            mean = [sum(points[j][k] for j in ids)/len(ids) for k in range(3)]
            for j in ids:
                points[j] = mean[:]
        return points, placements, joined

    def texture(self, block, ref, folder, animation_folder):
        from PIL import Image
        desc = self.payload(block, ref)
        require(self.kind(block, ref) == 0x44, 'Polygon texture reference is not a descriptor')
        dw, dh = struct.unpack_from('<2H', desc)
        pr, ir = struct.unpack_from('<2I', desc, 16)
        require(self.kind(block, pr) == 0x47 and self.kind(block, ir) == 0x48, 'Invalid image/palette links')
        pal, img = self.payload(block, pr), self.payload(block, ir)
        ver, w, h, image_n = struct.unpack_from('<4H', img)
        palette_flags = u16(pal, 2)
        n = palette_flags & 0x7fff
        # The image count word also carries effect/animation flags. The linked
        # palette and actual pixel indices are authoritative for its colour count.
        require(ver == 1 and u16(pal) == 1 and 1 <= n <= 256,
                f'Unsupported native image/palette format at {block}/{ref}: version={ver}, palette={n}, image={image_n}')
        require(len(pal) == 4+n*3 and len(img)-12 in (w*h//2, w*h), 'Invalid image or palette byte count')
        require(dw == w and dh > 0 and h % dh == 0, 'Descriptor/image dimensions do not agree')
        indices = bytearray()
        if len(img)-12 == w*h:
            indices.extend(img[12:])
        else:
            for value in img[12:]:
                indices.extend((value & 15, value >> 4))
        require(max(indices, default=0) < n, 'Texture index exceeds palette')
        palette = [min(255, c*255//63) for c in pal[4:]]
        palette.extend([0]*(768-len(palette)))
        im = Image.frombytes('P', (w, h), bytes(indices))
        im.putpalette(palette)
        if palette_flags & 0x8000:
            # SLUS palette loader explicitly writes CLUT entry zero as transparent.
            im.info['transparency'] = 0
            im = im.convert('RGBA')
        else:
            im = im.convert('RGB')
        stem = f'image_{ir:05d}_palette_{pr:05d}_descriptor_{ref:05d}'
        name = stem + ('_frame00.png' if h > dh else '.png')
        im.crop((0, 0, w, dh)).save(folder / name)
        if h > dh:
            animation_folder.mkdir(parents=True, exist_ok=True)
            im.save(animation_folder / (stem+'_native_strip.png'))
            for j in range(h//dh):
                im.crop((0, j*dh, w, (j+1)*dh)).save(animation_folder / (stem+f'_frame{j:02d}.png'))
        return name, bool(palette_flags & 0x8000)

    def export_level(self, block, map_ref, destination, name, repair=True):
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        texture_folder = destination / 'textures'
        texture_folder.mkdir(exist_ok=True)
        obj_path, mtl_path = destination/(name+'.obj'), destination/(name+'.mtl')
        stats = Counter()
        mats = {}
        mtl_lines = []
        points, placements, joined = self.placed_environment(block, map_ref, repair)
        with obj_path.open('w', encoding='utf-8', newline='\n') as obj:
            obj.write(f'mtllib {name}.mtl\n')
            for x, z, layer, ref, offset, count in placements:
                    vertices, faces, scale = self.mesh(block, ref)
                    # Native column transform R(+quarter turn), followed by scene Z reflection.
                    off = stats['vertices']
                    for xx, yy, zz in points[offset:offset+count]:
                        obj.write(f'v {xx:.8f} {yy:.8f} {zz:.8f}\n')
                    stats['vertices'] += len(vertices)
                    stats['instances'] += 1
                    group = None
                    for vs, uv, tex, rgb, op in faces:
                        category = 'Water_Surface' if layer == 2 else ('Shoreline_Foam' if op == 2 else ('Terrain_and_Structures' if layer == 0 else 'Seabed'))
                        face_group = f'{category}_tile_{x:03d}_{z:03d}_layer_{layer}_resource_{ref:05d}'
                        if face_group != group:
                            obj.write('o '+face_group+'\n')
                            group = face_group
                        key = ('texture', tex) if tex is not None else ('colour', rgb)
                        if key not in mats:
                            material = f'Material_{len(mats):03d}'
                            mats[key] = material
                            mtl_lines.append('newmtl '+material)
                            if tex is not None:
                                image, alpha = self.texture(block, tex, texture_folder, destination/'Native_Animation_Frames')
                                mtl_lines.extend(('Kd 1 1 1', 'map_Kd textures/'+image))
                                if alpha:
                                    mtl_lines.append('map_d -imfchan a textures/'+image)
                            else:
                                mtl_lines.append('Kd '+' '.join(f'{min(1, c/63):.8f}' for c in rgb))
                            mtl_lines.extend(('Ks 0 0 0', 'illum 1', ''))
                        obj.write('usemtl '+mats[key]+'\n')
                        if len(vs) < 3:
                            obj.write('p '+' '.join(str(k+off+1) for k in vs)+'\n')
                            stats['points'] += 1
                        elif uv is not None:
                            require(len(uv) == len(vs), 'UV corner count does not match polygon')
                            for u, v in uv:
                                obj.write(f'vt {u/255:.9f} {1-v/255:.9f}\n')
                            obj.write('f '+' '.join(f'{vi+off+1}/{stats["uvs"]+j+1}' for j, vi in enumerate(vs))+'\n')
                            stats['uvs'] += len(uv)
                            stats['faces'] += 1
                        else:
                            obj.write('f '+' '.join(str(vi+off+1) for vi in vs)+'\n')
                            stats['faces'] += 1
                        stats[f'op_{op:02x}'] += 1
        mtl_path.write_text('\n'.join(mtl_lines)+'\n', encoding='utf-8')
        validate_obj(obj_path, stats)
        stats['boundary_links'] = joined
        print(f'{name}: {stats["faces"]:,} polygons, {stats["vertices"]:,} vertices, {len(mats)} materials', flush=True)
        return dict(stats)


def validate_obj(path, expected=None):
    """Check every emitted index, material and texture dependency."""
    path = Path(path)
    nv = nt = nf = np = 0
    known, used = set(), set()
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            s = line.split()
            if not s:
                continue
            if s[0] == 'v':
                nv += 1
            elif s[0] == 'vt':
                nt += 1
            elif s[0] == 'mtllib':
                mtl = path.parent/s[1]
                require(mtl.is_file(), f'Missing material file: {mtl}')
                for ml in mtl.read_text(encoding='utf-8').splitlines():
                    t = ml.split()
                    if t and t[0] == 'newmtl':
                        known.add(t[1])
                    elif t and t[0] in ('map_Kd', 'map_d'):
                        require((path.parent/t[-1]).is_file(), f'Missing texture: {t[-1]}')
            elif s[0] == 'usemtl':
                used.add(s[1])
            elif s[0] in ('f', 'p', 'l'):
                nf += s[0] == 'f'
                np += s[0] == 'p'
                for corner in s[1:]:
                    ids = corner.split('/')
                    require(1 <= int(ids[0]) <= nv, 'Invalid exported vertex index')
                    if len(ids) > 1:
                        require(1 <= int(ids[1]) <= nt, 'Invalid exported UV index')
    require(used <= known, 'OBJ refers to undefined materials')
    if expected is not None:
        require(nv == expected['vertices'] and nt == expected['uvs'] and
                nf == expected['faces'] and np == expected['points'], 'Exported primitive totals disagree with source totals')
    return nv, nt
