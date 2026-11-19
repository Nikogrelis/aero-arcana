package com.aeroarcana.climatebridge;

import com.momosoftworks.coldsweat.api.event.core.init.DefaultTempModifiersEvent;
import com.momosoftworks.coldsweat.api.event.core.registry.TempModifierRegisterEvent;
import com.momosoftworks.coldsweat.api.temperature.modifier.CaveBiomeTempModifier;
import com.momosoftworks.coldsweat.api.util.Temperature;
import com.momosoftworks.coldsweat.api.util.placement.Mode;
import com.momosoftworks.coldsweat.api.util.placement.Order;
import com.momosoftworks.coldsweat.api.util.placement.Placement;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.entity.player.Player;
import net.neoforged.bus.api.EventPriority;
import net.neoforged.bus.api.IEventBus;
import net.neoforged.fml.common.Mod;
import net.neoforged.neoforge.common.NeoForge;

/**
 * Aero Arcana climate bridge: Create Atmospherics owns the climate (season, weather, biome, altitude, time of day,
 * wind chill, greenhouses); Cold Sweat owns the player's body (gauge, damage, clothing, items, nearby blocks).
 *
 * For players, a WORLD-trait modifier is inserted right after Cold Sweat's cave modifier and replaces the value
 * produced so far (biome + elevation + shade + cave) with Atmospherics' air temperature. Modifiers after it
 * (blocks, entities, hearths, waterskins, armour ...) keep working on top. In dimensions Atmospherics does not
 * simulate, the modifier passes the value through unchanged, so Cold Sweat's own model applies.
 */
@Mod(ClimateBridge.MODID)
public final class ClimateBridge {
    public static final String MODID = "aero_climate_bridge";
    public static final ResourceLocation MODIFIER_ID = ResourceLocation.fromNamespaceAndPath(MODID, "atmospherics_climate");

    public ClimateBridge(IEventBus modBus) {
        NeoForge.EVENT_BUS.addListener(ClimateBridge::onRegisterModifiers);
        NeoForge.EVENT_BUS.addListener(EventPriority.LOWEST, ClimateBridge::onDefaultModifiers);
    }

    private static void onRegisterModifiers(TempModifierRegisterEvent event) {
        event.register(MODIFIER_ID, AtmosphericsClimateTempModifier::new);
    }

    private static void onDefaultModifiers(DefaultTempModifiersEvent event) {
        if (!(event.getEntity() instanceof Player)) {
            return;
        }
        Placement after = Placement.of(Mode.ADD_AFTER, Order.LAST, m -> m instanceof CaveBiomeTempModifier)
                .orElse(Placement.LAST);
        event.addModifier(Temperature.Trait.WORLD, new AtmosphericsClimateTempModifier().tickRate(20), after);
    }
}
