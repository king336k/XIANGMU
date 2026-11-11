package com.transcengram.bridge_validation;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.transcengram.data_platform.controller.*;
import com.transcengram.data_platform.interceptor.*;
import com.transcengram.data_platform.resolver.UserInfoArgumentResolver;
import com.transcengram.data_platform.service.*;
import com.transcengram.data_platform.service.Imp.UserServiceImpl;
import com.transcengram.data_platform.utils.RedisUtil;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;
import java.util.List;

/** Runs the selected branch's production IAM/bridge/context code against isolated databases. */
@SpringBootConfiguration
@EnableAutoConfiguration
@MapperScan("com.transcengram.data_platform.mapper")
@Import({IssueIdentityBridgeService.class, IssueBridgeRequestAuthorizer.class,
        IssueDataPackageLookupService.class, IssueIntegrationTokenValidator.class,
        InternalIssueContextController.class, InternalIssueCatalogController.class,
        InternalIssueUserController.class, InternalIssuePermissionController.class,
        IssueIdentityBridgeController.class, DaqAuthController.class, DaqTokenService.class})
public class BridgeValidationApplication {
    public static void main(String[] args) { SpringApplication.run(BridgeValidationApplication.class, args); }
    @Bean ObjectMapper objectMapper() {
        return new ObjectMapper().findAndRegisterModules()
                .disable(com.fasterxml.jackson.databind.SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    }
    @Bean RedisUtil redisUtil() { return new RedisUtil(); }
    @Bean UserService userService() { return new UserServiceImpl(); }
    @Bean UserController userController() { return new UserController(); }
    @Bean AuthInterceptor authInterceptor() { return new AuthInterceptor(); }
    @Bean RoleInterceptor roleInterceptor() { return new RoleInterceptor(); }
    @Bean UserInfoArgumentResolver userInfoArgumentResolver() { return new UserInfoArgumentResolver(); }
    @Bean DaqTokenInterceptor daqInterceptor(DaqTokenService tokens,
            com.transcengram.data_platform.mapper.UserMapper users, RedisUtil redis, ObjectMapper mapper) {
        return new DaqTokenInterceptor(tokens, users, redis, mapper);
    }
    @Bean WebMvcConfigurer authentication(AuthInterceptor auth, DaqTokenInterceptor daq,
            RoleInterceptor roles, UserInfoArgumentResolver resolver) {
        return new WebMvcConfigurer() {
            public void addInterceptors(InterceptorRegistry registry) {
                registry.addInterceptor(auth).addPathPatterns("/**").excludePathPatterns("/error", "/internal/**").order(1);
                registry.addInterceptor(daq).addPathPatterns("/api/user/**", "/issue-api/**").order(2);
                registry.addInterceptor(roles).addPathPatterns("/**").excludePathPatterns("/error", "/internal/**").order(3);
            }
            public void addArgumentResolvers(List<HandlerMethodArgumentResolver> resolvers) { resolvers.add(resolver); }
        };
    }
}
