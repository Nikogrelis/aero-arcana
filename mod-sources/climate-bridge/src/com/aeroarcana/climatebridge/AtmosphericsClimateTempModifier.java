package com.aeroarcana.climatebridge;

import com.enzonic.aeronauticswinds.WindsSim;
import com.enzonic.aeronauticswinds.season.GreenhouseDetector;
import com.momosoftworks.coldsweat.api.temperature.modifier.TempModifier;
import com.momosoftworks.coldsweat.api.util.Temperature;
import net.minecraft.core.BlockPos;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.level.Level;
import org.joml.Vector3d;

import java.util.function.Function;

/**
 * Replaces Cold Sweat's ambient (biome/elevation/shade/cave) temperature with Create Atmospherics' climate.
 * Uses only the climate part of Atmospherics' player exposure: no nearby blocks, water, rain, fire or sprinting,
 * because Cold Sweat already accounts for those (otherwise they would be counted twice).
 */
public class AtmosphericsClimateTempModifier extends TempModifier {
    private static final Function<Double, Double> PASS = t -> t;

    @Override
    protected Function<Double, Double> calculate(LivingEntity entity, Temperature.Trait trait) {
        try {
            Level level = entity.level();
            WindsSim.Simulation sim = WindsSim.forLevel(level);
            if (sim == null) {
                return PASS;
            }
            double x = entity.getX(), y = entity.getY(), z = entity.getZ();
            double c = sim.temperatureC(level, x, y, z);
            if (Double.isNaN(c) || Double.isInfinite(c)) {
                return PASS;
            }
            BlockPos pos = entity.blockPosition();
            GreenhouseDetector.GreenhouseInfo greenhouse = GreenhouseDetector.checkGreenhouse(level, pos);
            if (greenhouse != null && greenhouse.isGreenhouse()) {
                c += greenhouse.heatBonusC();
            }
            // Atmospherics' wind chill: exposed to the sky and below 10 C, wind cools by up to 10 C.
            if (c < 10.0 && level.canSeeSky(pos)) {
                Vector3d wind = sim.sampleWind(level, x, y, z);
                double speed = Math.sqrt(wind.x * wind.x + wind.z * wind.z);
                c -= Math.min(10.0, speed * 0.22);
            }
            double mc = Temperature.convert(c, Temperature.Units.C, Temperature.Units.MC, true);
            return t -> mc;
        } catch (Throwable t) {
            // Never break Cold Sweat's own model if Atmospherics changes or is not ready yet.
            return PASS;
        }
    }
}
