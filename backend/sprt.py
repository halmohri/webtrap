import math


class SPRT:
    def __init__(self, mu0, sigma0, mu1, sigma1, log_A, log_B):
        self.mu0    = mu0
        self.sigma0 = sigma0
        self.mu1    = mu1
        self.sigma1 = sigma1
        self.log_A  = log_A
        self.log_B  = log_B
        self.E    = 0.0

    def step(self, c):
        log_p_normal = (-math.log(self.sigma0 * math.sqrt(2 * math.pi))
                        - ((c - self.mu0) ** 2) / (2 * self.sigma0 ** 2))
        log_p_attack = (-math.log(self.sigma1 * math.sqrt(2 * math.pi))
                        - ((c - self.mu1) ** 2) / (2 * self.sigma1 ** 2))

        delta = log_p_attack - log_p_normal
        self.E += delta

        decision = ""
        if self.E >= self.log_A:
            decision = "DETECTED"
            self.E = 0.0
        elif self.E <= self.log_B:
            decision = "REJECTED"
            self.E = 0.0
        else: 
            decision = "NONE"

        return c, delta, decision
