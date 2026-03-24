package com.finguardx.security;

import io.jsonwebtoken.*;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.stereotype.Component;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;
import org.springframework.web.filter.OncePerRequestFilter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.http.*;
import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.*;

/**
 * JWT utility — SRS §5: JWT-based authentication with session timeout.
 * Every token carries: sub (userId), tenant (tenantCode), role.
 */
@Component
public class JwtUtil {

    @Value("${app.jwt.secret}")
    private String secret;

    @Value("${app.jwt.access-token-expiry-minutes:60}")
    private int accessExpiryMinutes;

    @Value("${app.jwt.refresh-token-expiry-days:7}")
    private int refreshExpiryDays;

    private SecretKey key() {
        return Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
    }

    public String generateAccessToken(UUID userId, String tenantCode, String role) {
        return Jwts.builder()
                .subject(userId.toString())
                .claim("tenant", tenantCode)
                .claim("role", role)
                .claim("type", "access")
                .id(UUID.randomUUID().toString())
                .issuedAt(Date.from(Instant.now()))
                .expiration(Date.from(Instant.now().plus(accessExpiryMinutes, ChronoUnit.MINUTES)))
                .signWith(key())
                .compact();
    }

    public String generateRefreshToken(UUID userId) {
        return Jwts.builder()
                .subject(userId.toString())
                .claim("type", "refresh")
                .id(UUID.randomUUID().toString())
                .issuedAt(Date.from(Instant.now()))
                .expiration(Date.from(Instant.now().plus(refreshExpiryDays, ChronoUnit.DAYS)))
                .signWith(key())
                .compact();
    }

    public Claims validateToken(String token) {
        return Jwts.parser().verifyWith(key()).build()
                .parseSignedClaims(token).getPayload();
    }

    public String extractUserId(Claims claims)     { return claims.getSubject(); }
    public String extractTenantCode(Claims claims) { return claims.get("tenant", String.class); }
    public String extractRole(Claims claims)        { return claims.get("role", String.class); }
    public String extractType(Claims claims)        { return claims.get("type", String.class); }
}

/**
 * JWT Request Filter — validates token on every protected request.
 * Enforces tenant isolation by attaching tenant context to security principal.
 */
@Component
class JwtAuthFilter extends OncePerRequestFilter {

    private final JwtUtil jwtUtil;
    private final Set<String> revokedTokens = Collections.synchronizedSet(new HashSet<>());

    public JwtAuthFilter(JwtUtil jwtUtil) { this.jwtUtil = jwtUtil; }

    public void revokeToken(String token) { revokedTokens.add(token); }
    public boolean isRevoked(String token) { return revokedTokens.contains(token); }

    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res,
                                     FilterChain chain) throws java.io.IOException, jakarta.servlet.ServletException {
        String header = req.getHeader("Authorization");
        if (header != null && header.startsWith("Bearer ")) {
            String token = header.substring(7);
            if (!isRevoked(token)) {
                try {
                    var claims = jwtUtil.validateToken(token);
                    if ("access".equals(jwtUtil.extractType(claims))) {
                        var auth = new UsernamePasswordAuthenticationToken(
                            claims,
                            null,
                            List.of(new SimpleGrantedAuthority("ROLE_" + jwtUtil.extractRole(claims)))
                        );
                        SecurityContextHolder.getContext().setAuthentication(auth);
                    }
                } catch (JwtException ignored) { /* invalid token → unauthenticated */ }
            }
        }
        chain.doFilter(req, res);
    }
}

/**
 * Security configuration — SRS §5: JWT-based security, no server sessions.
 */
@Configuration
@EnableWebSecurity
class SecurityConfig {

    private final JwtAuthFilter jwtAuthFilter;

    SecurityConfig(JwtAuthFilter jwtAuthFilter) { this.jwtAuthFilter = jwtAuthFilter; }

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        return http
            .csrf(AbstractHttpConfigurer::disable)
            .cors(cors -> cors.configurationSource(corsConfigurationSource()))
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                // Public endpoints
                .requestMatchers("/api/auth/login", "/api/auth/refresh",
                                  "/api/tenants", "/api/health",
                                  "/actuator/health").permitAll()
                // All other endpoints require authentication
                .anyRequest().authenticated()
            )
            .addFilterBefore(jwtAuthFilter, UsernamePasswordAuthenticationFilter.class)
            .build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() { return new BCryptPasswordEncoder(12); }

    @Bean
    CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOriginPatterns(List.of("*"));
        config.setAllowedMethods(List.of("GET","POST","PUT","DELETE","OPTIONS"));
        config.setAllowedHeaders(List.of("*"));
        config.setAllowCredentials(false);
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }
}
