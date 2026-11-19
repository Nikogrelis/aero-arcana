import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;

import java.io.*;
import java.util.zip.*;

/**
 * Patches "Ice and Fire: Dragon Care" 1.3.1 (MIT licence):
 *  1. DragonHunterGuildPlacer / VillageForgePlacer .onChunkLoad ignore chunks farther than 10M blocks from 0,0.
 *     Sable keeps its physics sub-levels around 20M blocks; Dragon Care treated them as terrain and tried to
 *     build a Dragon Hunter Guild there (thousands of PLACE-BLOCK-FAIL warnings).
 *  2. VillageForgePlacer.attemptScan loads the chunk (getChunk(..., FULL, true)) instead of giving up when it is
 *     already unloaded. With fast pregeneration (Chunky, C2ME) chunks unload before the scan reaches them and
 *     village forges were silently skipped.
 * Usage: java -cp asm.jar;asm-tree.jar;. DragonCarePatch in.jar out.jar
 */
public class DragonCarePatch {
    static final String FIX = "com/dragoncare/compat/AeroArcanaFix";
    static final String LOAD = "net/neoforged/neoforge/event/level/ChunkEvent$Load";
    static final int FAR_CHUNKS = 625_000; // 10,000,000 blocks

    public static void main(String[] a) throws Exception {
        int guards = 0, loads = 0;
        try (ZipInputStream in = new ZipInputStream(new FileInputStream(a[0]));
             ZipOutputStream out = new ZipOutputStream(new FileOutputStream(a[1]))) {
            ZipEntry e;
            while ((e = in.getNextEntry()) != null) {
                byte[] data = in.readAllBytes();
                String n = e.getName();
                if (n.equals("com/dragoncare/worldgen/DragonHunterGuildPlacer.class")
                        || n.equals("com/dragoncare/worldgen/VillageForgePlacer.class")) {
                    ClassNode cn = new ClassNode();
                    new ClassReader(data).accept(cn, ClassReader.EXPAND_FRAMES);
                    for (MethodNode m : cn.methods) {
                        if (m.name.equals("onChunkLoad") && m.desc.equals("(L" + LOAD + ";)V")) {
                            LabelNode cont = new LabelNode();
                            InsnList g = new InsnList();
                            g.add(new VarInsnNode(Opcodes.ALOAD, 0));
                            g.add(new MethodInsnNode(Opcodes.INVOKESTATIC, FIX, "isFar", "(L" + LOAD + ";)Z", false));
                            g.add(new JumpInsnNode(Opcodes.IFEQ, cont));
                            g.add(new InsnNode(Opcodes.RETURN));
                            g.add(cont);
                            g.add(new FrameNode(Opcodes.F_NEW, 1, new Object[]{LOAD}, 0, new Object[0]));
                            m.instructions.insert(g);
                            m.maxStack = Math.max(m.maxStack, 1);
                            guards++;
                        }
                        if (m.name.equals("attemptScan")) {
                            for (AbstractInsnNode i : m.instructions.toArray()) {
                                if (i instanceof MethodInsnNode mi && mi.owner.equals("net/minecraft/server/level/ServerChunkCache")
                                        && mi.name.equals("getChunk") && mi.desc.startsWith("(IILnet/minecraft/world/level/chunk/status/ChunkStatus;Z)")) {
                                    AbstractInsnNode prev = mi.getPrevious();
                                    if (prev.getOpcode() != Opcodes.ICONST_0) throw new IllegalStateException("unexpected bytecode before getChunk");
                                    m.instructions.set(prev, new InsnNode(Opcodes.ICONST_1));
                                    loads++;
                                }
                            }
                        }
                    }
                    ClassWriter cw = new ClassWriter(0);
                    cn.accept(cw);
                    data = cw.toByteArray();
                }
                out.putNextEntry(new ZipEntry(n));
                out.write(data);
            }
            out.putNextEntry(new ZipEntry(FIX + ".class"));
            out.write(fixClass());
        }
        System.out.println("chunk-load guards: " + guards + ", scan loads: " + loads);
        if (guards != 2 || loads != 1) throw new IllegalStateException("unexpected patch count");
    }

    /** isFar(event) = max(|x|,|z|) of the chunk > FAR_CHUNKS, written without branches. */
    static byte[] fixClass() {
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cw.visit(Opcodes.V21, Opcodes.ACC_PUBLIC | Opcodes.ACC_FINAL | Opcodes.ACC_SUPER, FIX, null, "java/lang/Object", null);
        MethodVisitor mv = cw.visitMethod(Opcodes.ACC_PUBLIC | Opcodes.ACC_STATIC, "isFar", "(L" + LOAD + ";)Z", null, null);
        mv.visitCode();
        mv.visitVarInsn(Opcodes.ALOAD, 0);
        mv.visitMethodInsn(Opcodes.INVOKEVIRTUAL, LOAD, "getChunk", "()Lnet/minecraft/world/level/chunk/ChunkAccess;", false);
        mv.visitMethodInsn(Opcodes.INVOKEVIRTUAL, "net/minecraft/world/level/chunk/ChunkAccess", "getPos", "()Lnet/minecraft/world/level/ChunkPos;", false);
        mv.visitInsn(Opcodes.DUP);
        mv.visitFieldInsn(Opcodes.GETFIELD, "net/minecraft/world/level/ChunkPos", "x", "I");
        mv.visitMethodInsn(Opcodes.INVOKESTATIC, "java/lang/Math", "abs", "(I)I", false);
        mv.visitInsn(Opcodes.SWAP);
        mv.visitFieldInsn(Opcodes.GETFIELD, "net/minecraft/world/level/ChunkPos", "z", "I");
        mv.visitMethodInsn(Opcodes.INVOKESTATIC, "java/lang/Math", "abs", "(I)I", false);
        mv.visitMethodInsn(Opcodes.INVOKESTATIC, "java/lang/Math", "max", "(II)I", false);
        mv.visitLdcInsn(FAR_CHUNKS);
        mv.visitInsn(Opcodes.SWAP);
        mv.visitInsn(Opcodes.ISUB);           // FAR - max  (< 0 when far)
        mv.visitIntInsn(Opcodes.BIPUSH, 31);
        mv.visitInsn(Opcodes.IUSHR);          // sign bit -> 1 when far
        mv.visitInsn(Opcodes.IRETURN);
        mv.visitMaxs(0, 0);
        mv.visitEnd();
        cw.visitEnd();
        return cw.toByteArray();
    }
}
