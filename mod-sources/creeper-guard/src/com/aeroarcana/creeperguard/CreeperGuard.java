package com.aeroarcana.creeperguard;

import net.minecraft.world.entity.decoration.ArmorStand;
import net.minecraft.world.entity.decoration.HangingEntity;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.entity.monster.Creeper;
import net.neoforged.bus.api.IEventBus;
import net.neoforged.fml.common.Mod;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.level.ExplosionEvent;

/**
 * Aero Arcana creeper guard: creeper explosions still hurt players and mobs, but break no blocks and
 * do not destroy item frames, paintings, armour stands or dropped items. Other explosions are untouched.
 */
@Mod("aero_creeper_guard")
public final class CreeperGuard {
    public CreeperGuard(IEventBus modBus) {
        NeoForge.EVENT_BUS.addListener(CreeperGuard::onDetonate);
    }

    private static void onDetonate(ExplosionEvent.Detonate event) {
        if (!(event.getExplosion().getDirectSourceEntity() instanceof Creeper)) {
            return;
        }
        event.getAffectedBlocks().clear();
        event.getAffectedEntities().removeIf(e -> e instanceof HangingEntity || e instanceof ArmorStand || e instanceof ItemEntity);
    }
}
