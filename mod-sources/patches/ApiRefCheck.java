import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;

import java.io.*;
import java.util.*;
import java.util.zip.*;

/**
 * Lists method/field references from an addon jar into a library package that do not resolve in the library jar.
 * Usage: java ApiRefCheck addon.jar lib.jar rbasamoyai/createbigcannons/
 */
public class ApiRefCheck {
    static Map<String, ClassNode> lib = new HashMap<>();

    static Map<String, ClassNode> load(String jar) throws IOException {
        Map<String, ClassNode> m = new HashMap<>();
        try (ZipInputStream in = new ZipInputStream(new FileInputStream(jar))) {
            ZipEntry e;
            while ((e = in.getNextEntry()) != null)
                if (e.getName().endsWith(".class")) {
                    ClassNode cn = new ClassNode();
                    new ClassReader(in.readAllBytes()).accept(cn, ClassReader.SKIP_CODE);
                    m.put(cn.name, cn);
                }
        }
        return m;
    }

    static boolean has(String owner, String name, String desc, boolean field, Set<String> seen) {
        ClassNode c = lib.get(owner);
        if (c == null || !seen.add(owner)) return c == null; // outside lib: cannot judge, assume ok
        if (field) { for (FieldNode f : c.fields) if (f.name.equals(name) && f.desc.equals(desc)) return true; }
        else for (MethodNode m : c.methods) if (m.name.equals(name) && m.desc.equals(desc)) return true;
        if (c.superName != null && lib.containsKey(c.superName) && has(c.superName, name, desc, field, seen)) return true;
        for (String i : c.interfaces) if (lib.containsKey(i) && has(i, name, desc, field, seen)) return true;
        // inherits from something outside lib (e.g. Create/Minecraft) -> assume resolvable there
        if (c.superName != null && !lib.containsKey(c.superName) && !c.superName.equals("java/lang/Object")) return true;
        for (String i : c.interfaces) if (!lib.containsKey(i)) return true;
        return false;
    }

    public static void main(String[] a) throws Exception {
        lib = load(a[1]);
        String pkg = a[2];
        Set<String> bad = new TreeSet<>();
        try (ZipInputStream in = new ZipInputStream(new FileInputStream(a[0]))) {
            ZipEntry e;
            while ((e = in.getNextEntry()) != null) {
                if (!e.getName().endsWith(".class")) continue;
                ClassNode cn = new ClassNode();
                new ClassReader(in.readAllBytes()).accept(cn, 0);
                for (MethodNode m : cn.methods)
                    for (AbstractInsnNode i : m.instructions) {
                        if (i instanceof MethodInsnNode mi && mi.owner.startsWith(pkg)) {
                            if (!lib.containsKey(mi.owner)) bad.add("missing class " + mi.owner + "  <- " + cn.name);
                            else if (!has(mi.owner, mi.name, mi.desc, false, new HashSet<>()))
                                bad.add("missing method " + mi.owner + "." + mi.name + mi.desc + "  <- " + cn.name);
                        } else if (i instanceof FieldInsnNode fi && fi.owner.startsWith(pkg)) {
                            if (!lib.containsKey(fi.owner)) bad.add("missing class " + fi.owner + "  <- " + cn.name);
                            else if (!has(fi.owner, fi.name, fi.desc, true, new HashSet<>()))
                                bad.add("missing field " + fi.owner + "." + fi.name + " " + fi.desc + "  <- " + cn.name);
                        } else if (i instanceof TypeInsnNode ti && ti.desc.startsWith(pkg) && !lib.containsKey(ti.desc)) {
                            bad.add("missing class " + ti.desc + "  <- " + cn.name);
                        }
                    }
                if (cn.superName != null && cn.superName.startsWith(pkg) && !lib.containsKey(cn.superName))
                    bad.add("missing superclass " + cn.superName + "  <- " + cn.name);
            }
        }
        bad.forEach(System.out::println);
        System.out.println("unresolved references: " + bad.size());
    }
}
