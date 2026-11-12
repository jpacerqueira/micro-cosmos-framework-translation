package com.customer.can.userauth.service;

import com.customer.can.userauth.domain.AppUser;
import com.customer.can.userauth.repository.AppUserRepository;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Date;
import java.util.List;
import java.util.Optional;

@Service
public class UserService {
    private static final Logger log = LogManager.getLogger(UserService.class);

    private final AppUserRepository userRepository;
    private final BCryptPasswordEncoder passwordEncoder;

    public UserService(AppUserRepository userRepository) {
        this.userRepository = userRepository;
        this.passwordEncoder = new BCryptPasswordEncoder();
    }

    public List<AppUser> findAll() {
        return userRepository.findAll();
    }

    public Optional<AppUser> findById(String id) {
        return userRepository.findById(id);
    }

    public Optional<AppUser> findByEmail(String email) {
        return userRepository.findByEmail(email);
    }

    @Transactional
    public AppUser create(AppUser user) {
        user.setPasswordHash(passwordEncoder.encode(user.getPasswordHash()));
        AppUser saved = userRepository.save(user);
        log.info("action=user_created email={}", saved.getEmail());
        return saved;
    }

    public boolean authenticate(String email, String rawPassword) {
        return userRepository.findByEmailAndActive(email, 1)
                .map(u -> passwordEncoder.matches(rawPassword, u.getPasswordHash()))
                .orElse(false);
    }

    @Transactional
    public void recordLogin(String email) {
        userRepository.findByEmail(email).ifPresent(u -> {
            u.setLastLogin(new Date());
            userRepository.save(u);
        });
    }
}
