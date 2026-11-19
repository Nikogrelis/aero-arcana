import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;

/**
 * Patches CBC Advanced Technologies 0.1.4c for Create Big Cannons 5.11+.
 * CBC changed ControlPitchContraption.onRecoil(Vec3, ACE) to onRecoil(Vec3 recoil, Vec3 pos, ACE).
 * Every old call is redirected to RecoilFix.onRecoil, which passes the contraption entity position as pos.
 * Usage: java -cp asm.jar;asm-tree.jar;. CbcAtRecoilPatch in.jar out.jar
 */
public class CbcAtRecoilPatch {
    static final String CPC = "rbasamoyai/createbigcannons/cannon_control/ControlPitchContraption";
    static final String ACE = "com/simibubi/create/content/contraptions/AbstractContraptionEntity";
    static final String VEC = "net/minecraft/world/phys/Vec3";
    static final String OLD = "(L" + VEC + ";L" + ACE + ";)V";
    static final String NEW = "(L" + VEC + ";L" + VEC + ";L" + ACE + ";)V";
    static final String FIX = "com/dsvv/cbcat/compat/RecoilFix";
    static final String PBDM = "rbasamoyai/createbigcannons/base/PartialBlockDamageManager";
    static final String DMG_TAIL = "Lnet/minecraft/world/level/block/state/BlockState;Lnet/minecraft/world/level/Level;)Z";
    static final String DMG_OLD = "(Lnet/minecraft/core/BlockPos;I" + DMG_TAIL;
    static final String DMG_NEW = "(Lnet/minecraft/core/BlockPos;F" + DMG_TAIL;

    public static void main(String[] a) throws Exception {
        int patched = 0;
        try (ZipInputStream in = new ZipInputStream(new FileInputStream(a[0]));
             ZipOutputStream out = new ZipOutputStream(new FileOutputStream(a[1]))) {
            ZipEntry e;
            while ((e = in.getNextEntry()) != null) {
                byte[] data = in.readAllBytes();
                if (e.getName().endsWith(".class")) {
                    ClassReader cr = new ClassReader(data);
                    ClassNode cn = new ClassNode();
                    cr.accept(cn, 0);
                    int n = 0;
                    for (MethodNode m : cn.methods)
                        for (AbstractInsnNode i : m.instructions.toArray())
                            if (i instanceof MethodInsnNode mi && mi.owner.equals(CPC) && mi.name.equals("onRecoil") && mi.desc.equals(OLD)) {
                                m.instructions.set(mi, new MethodInsnNode(Opcodes.INVOKESTATIC, FIX, "onRecoil",
                                        "(L" + CPC + ";L" + VEC + ";L" + ACE + ";)V", false));
                                n++;
                            } else if (i instanceof MethodInsnNode mi && mi.owner.equals(PBDM) && mi.name.equals("damageBlock") && mi.desc.equals(DMG_OLD)) {
                                m.instructions.set(mi, new MethodInsnNode(Opcodes.INVOKESTATIC, FIX, "damageBlock",
                                        "(L" + PBDM + ";" + DMG_OLD.substring(1), false));
                                n++;
                            }
                    if (n > 0) {
                        ClassWriter cw = new ClassWriter(0);
                        cn.accept(cw);
                        data = cw.toByteArray();
                        System.out.println("patched " + cn.name + " x" + n);
                        patched += n;
                    }
                }
                out.putNextEntry(new ZipEntry(e.getName()));
                out.write(data);
            }
            out.putNextEntry(new ZipEntry(FIX + ".class"));
            out.write(fixClass());
        }
        if (patched == 0) throw new IllegalStateException("nothing patched");
        System.out.println("total call sites: " + patched);
    }

    static byte[] fixClass() {
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cw.visit(Opcodes.V21, Opcodes.ACC_PUBLIC | Opcodes.ACC_FINAL | Opcodes.ACC_SUPER, FIX, null, "java/lang/Object", null);
        MethodVisitor mv = cw.visitMethod(Opcodes.ACC_PUBLIC | Opcodes.ACC_STATIC, "onRecoil",
                "(L" + CPC + ";L" + VEC + ";L" + ACE + ";)V", null, null);
        mv.visitCode();
        mv.visitVarInsn(Opcodes.ALOAD, 0);
        mv.visitVarInsn(Opcodes.ALOAD, 1);
        mv.visitVarInsn(Opcodes.ALOAD, 2);
        mv.visitMethodInsn(Opcodes.INVOKEVIRTUAL, "net/minecraft/world/entity/Entity", "position", "()L" + VEC + ";", false);
        mv.visitVarInsn(Opcodes.ALOAD, 2);
        mv.visitMethodInsn(Opcodes.INVOKEINTERFACE, CPC, "onRecoil", NEW, true);
        mv.visitInsn(Opcodes.RETURN);
        mv.visitMaxs(0, 0);
        mv.visitEnd();
        // CBC 5.11 changed damageBlock(BlockPos, int, ...) to damageBlock(BlockPos, float, ...)
        mv = cw.visitMethod(Opcodes.ACC_PUBLIC | Opcodes.ACC_STATIC, "damageBlock", "(L" + PBDM + ";" + DMG_OLD.substring(1), null, null);
        mv.visitCode();
        mv.visitVarInsn(Opcodes.ALOAD, 0);
        mv.visitVarInsn(Opcodes.ALOAD, 1);
        mv.visitVarInsn(Opcodes.ILOAD, 2);
        mv.visitInsn(Opcodes.I2F);
        mv.visitVarInsn(Opcodes.ALOAD, 3);
        mv.visitVarInsn(Opcodes.ALOAD, 4);
        mv.visitMethodInsn(Opcodes.INVOKEVIRTUAL, PBDM, "damageBlock", DMG_NEW, false);
        mv.visitInsn(Opcodes.IRETURN);
        mv.visitMaxs(0, 0);
        mv.visitEnd();
        cw.visitEnd();
        return cw.toByteArray();
    }
}
